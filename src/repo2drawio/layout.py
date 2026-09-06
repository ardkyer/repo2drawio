from __future__ import annotations

from dataclasses import dataclass
from collections import defaultdict, deque

from .model import Architecture, Node


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    @property
    def center(self) -> tuple[float, float]:
        return self.x + self.width / 2, self.y + self.height / 2


@dataclass(frozen=True)
class Layout:
    nodes: dict[str, Box]
    groups: dict[str, Box]
    width: float
    height: float


def runtime_side_detour(layout: Layout, source_id: str) -> float | None:
    """Route below a support row when a rightward edge would cross a peer."""
    source = layout.nodes[source_id]
    peers = [box for key, box in layout.nodes.items() if key != source_id
             and box.x >= source.right and box.x < layout.groups["runtime"].right
             and box.y <= source.center[1] <= box.bottom]
    # A downward escape is safe only when there is no node below the source.
    below = any(box.y >= source.bottom and box.x <= source.center[0] <= box.right
                and box.y < layout.groups["runtime"].bottom
                for key, box in layout.nodes.items() if key != source_id)
    if peers and not below:
        return layout.groups["runtime"].bottom + 24.0
    return None


def _size(node: Node, theme: str = "classic") -> tuple[float, float]:
    longest = max(len(node.label), len(node.subtitle or ""))
    if theme in {"icon-sketch", "brand-logos"}:
        width = max(205.0, min(330.0, 130.0 + longest * 7.0))
        height = 92.0 if node.subtitle else 78.0
        return width, height
    width = max(150.0, min(280.0, 92.0 + longest * 7.0))
    height = 82.0 if node.subtitle else 64.0
    return width, height


def _ranks(architecture: Architecture) -> dict[str, int]:
    node_ids = [node.id for node in architecture.nodes]
    incoming: dict[str, int] = {node_id: 0 for node_id in node_ids}
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in architecture.edges:
        outgoing[edge.source].append(edge.target)
        incoming[edge.target] += 1

    queue = deque(node_id for node_id in node_ids if incoming[node_id] == 0)
    ranks = {node_id: 0 for node_id in node_ids}
    visited: set[str] = set()
    while queue:
        source = queue.popleft()
        visited.add(source)
        for target in outgoing[source]:
            ranks[target] = max(ranks[target], ranks[source] + 1)
            incoming[target] -= 1
            if incoming[target] == 0:
                queue.append(target)

    # Cycles are valid in architecture diagrams. Put unresolved nodes in stable
    # successive ranks instead of failing or looping forever.
    next_rank = max(ranks.values(), default=-1) + 1
    for node_id in node_ids:
        if node_id not in visited:
            ranks[node_id] = next_rank
            next_rank += 1
    return ranks


def _member_ranks(architecture: Architecture, members: set[str]) -> dict[str, int]:
    incoming = {node_id: 0 for node_id in members}
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in architecture.edges:
        if edge.source not in members or edge.target not in members:
            continue
        outgoing[edge.source].append(edge.target)
        incoming[edge.target] += 1
    queue = deque(sorted(node_id for node_id, count in incoming.items() if count == 0))
    ranks = {node_id: 0 for node_id in members}
    visited: set[str] = set()
    while queue:
        source = queue.popleft()
        visited.add(source)
        for target in outgoing[source]:
            ranks[target] = max(ranks[target], ranks[source] + 1)
            incoming[target] -= 1
            if incoming[target] == 0:
                queue.append(target)
    next_rank = max(ranks.values(), default=-1) + 1
    for node_id in sorted(members - visited):
        ranks[node_id] = next_rank
        next_rank += 1
    return ranks


FEATURE_LANES = ("domestic", "voucher", "assistant", "content")


def _feature_lane_layout(architecture: Architecture) -> Layout:
    """One-canvas layout organized around user-visible feature flows."""
    boxes: dict[str, Box] = {}
    group_boxes: dict[str, Box] = {}
    nodes = {node.id: node for node in architecture.nodes}
    canvas_left, runtime_top = 300.0, 100.0
    infrastructure = [node for node in architecture.nodes if node.parent == "infrastructure"]
    infrastructure_width = (
        sum(_size(node, architecture.theme)[0] for node in infrastructure)
        + max(0, len(infrastructure) - 1) * 58.0
        + 68.0
    )
    lane_width = max(1300.0, infrastructure_width)

    runtime_members = [node for node in architecture.nodes if node.parent == "runtime"]
    runtime_ids = {node.id for node in runtime_members}
    actor_entries = sorted(
        edge.target
        for edge in architecture.edges
        if edge.target in runtime_ids and nodes[edge.source].parent is None
    )
    incoming = {node_id: 0 for node_id in runtime_ids}
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in architecture.edges:
        if edge.source in runtime_ids and edge.target in runtime_ids:
            outgoing[edge.source].append(edge.target)
            incoming[edge.target] += 1
    entry = next(
        iter(actor_entries),
        next(iter(sorted(node_id for node_id, count in incoming.items() if count == 0)), None),
    )
    main_chain: list[str] = []
    current = entry
    while current and current not in main_chain:
        main_chain.append(current)
        successors = sorted(set(outgoing[current]))
        if len(successors) != 1 or incoming[successors[0]] != 1:
            break
        current = successors[0]
    main_chain.extend(node.id for node in runtime_members if node.id not in main_chain)

    runtime_y = runtime_top + 58.0
    cursor_x = canvas_left + 34.0
    for node_id in main_chain:
        node = nodes[node_id]
        width, height = _size(node, architecture.theme)
        boxes[node_id] = Box(cursor_x, runtime_y, width, height)
        cursor_x += width + 120.0
    runtime_height = max((_size(node, architecture.theme)[1] for node in runtime_members), default=92.0)
    group_boxes["runtime"] = Box(canvas_left, runtime_top, lane_width, runtime_height + 116.0)

    ungrouped = [node for node in architecture.nodes if node.parent is None]
    entry_y = runtime_y + runtime_height / 2
    cursor_y = entry_y - sum(_size(node, architecture.theme)[1] + 36.0 for node in ungrouped) / 2
    for node in sorted(ungrouped, key=lambda item: item.id):
        width, height = _size(node, architecture.theme)
        boxes[node.id] = Box(60.0, max(100.0, cursor_y), width, height)
        cursor_y += height + 36.0

    lane_y = group_boxes["runtime"].bottom + 62.0
    for group_id in FEATURE_LANES:
        if group_id not in {group.id for group in architecture.groups}:
            continue
        members = [node for node in architecture.nodes if node.parent == group_id]
        member_ids = {node.id for node in members}
        ranks = _member_ranks(architecture, member_ids)
        by_rank: dict[int, list[Node]] = defaultdict(list)
        for node in members:
            by_rank[ranks[node.id]].append(node)

        cursor_x = canvas_left + 34.0
        content_height = 0.0
        for rank in sorted(by_rank):
            rank_nodes = sorted(by_rank[rank], key=lambda item: item.id)
            column_width = max((_size(node, architecture.theme)[0] for node in rank_nodes), default=205.0)
            column_height = (
                sum(_size(node, architecture.theme)[1] for node in rank_nodes)
                + max(0, len(rank_nodes) - 1) * 28.0
            )
            cursor_node_y = lane_y + 58.0
            for node in rank_nodes:
                width, height = _size(node, architecture.theme)
                boxes[node.id] = Box(cursor_x, cursor_node_y, width, height)
                cursor_node_y += height + 28.0
            cursor_x += column_width + 116.0
            content_height = max(content_height, column_height)
        group_height = content_height + 116.0

        group_boxes[group_id] = Box(canvas_left, lane_y, lane_width, group_height)
        lane_y += group_height + 34.0

    if infrastructure:
        infra_y = lane_y + 28.0
        cursor_x = canvas_left + 34.0
        row_height = max((_size(node, architecture.theme)[1] for node in infrastructure), default=92.0)
        for node in sorted(infrastructure, key=lambda item: (item.kind, item.id)):
            width, height = _size(node, architecture.theme)
            boxes[node.id] = Box(cursor_x, infra_y + 58.0, width, height)
            cursor_x += width + 58.0
        group_boxes["infrastructure"] = Box(canvas_left, infra_y, lane_width, row_height + 116.0)

    integrations = [node for node in architecture.nodes if node.parent == "integrations"]
    if integrations:
        integration_left = canvas_left + lane_width + 150.0
        desired: list[tuple[float, Node]] = []
        for node in integrations:
            sources = [
                nodes[edge.source]
                for edge in architecture.edges
                if edge.target == node.id and edge.source in nodes
            ]
            source_group = next((source.parent for source in sources if source.parent in group_boxes), "runtime")
            source_box = group_boxes.get(source_group or "runtime", group_boxes["runtime"])
            desired.append((source_box.center[1], node))
        cursor_y = runtime_top + 58.0
        placed: list[Box] = []
        max_width = max(_size(node, architecture.theme)[0] for node in integrations)
        for target_y, node in sorted(desired, key=lambda item: (item[0], item[1].id)):
            width, height = _size(node, architecture.theme)
            y = max(cursor_y, target_y - height / 2)
            box = Box(integration_left + 34.0 + (max_width - width) / 2, y, width, height)
            boxes[node.id] = box
            placed.append(box)
            cursor_y = box.bottom + 44.0
        group_top = min(runtime_top, min(box.y for box in placed) - 58.0)
        group_bottom = max(box.bottom for box in placed) + 34.0
        group_boxes["integrations"] = Box(
            integration_left,
            group_top,
            max_width + 68.0,
            group_bottom - group_top,
        )

    remaining = [node for node in architecture.nodes if node.id not in boxes]
    remaining_y = max((box.bottom for box in group_boxes.values()), default=lane_y) + 50.0
    for node in remaining:
        width, height = _size(node, architecture.theme)
        boxes[node.id] = Box(canvas_left, remaining_y, width, height)
        remaining_y += height + 44.0

    all_boxes = list(boxes.values()) + list(group_boxes.values())
    width = max((box.right for box in all_boxes), default=1800.0) + 80.0
    height = max((box.bottom for box in all_boxes), default=1000.0) + 100.0
    return Layout(nodes=boxes, groups=group_boxes, width=width, height=height)


def _grouped_lr_layout(architecture: Architecture) -> Layout:
    runtime_members = [node for node in architecture.nodes if node.parent == "runtime"]
    member_ids = {node.id for node in runtime_members}
    boxes: dict[str, Box] = {}
    ungrouped = [node for node in architecture.nodes if node.parent is None]
    actor_width = max((_size(node, architecture.theme)[0] for node in ungrouped), default=0)
    runtime_left, runtime_top = max(300.0, 60.0 + actor_width + 134.0), 110.0
    incoming_runtime = {node_id: 0 for node_id in member_ids}
    outgoing_runtime: dict[str, list[str]] = defaultdict(list)
    incoming_from_outside: set[str] = set()
    for edge in architecture.edges:
        if edge.source in member_ids and edge.target in member_ids:
            outgoing_runtime[edge.source].append(edge.target)
            incoming_runtime[edge.target] += 1
        elif edge.target in member_ids and edge.source not in member_ids:
            incoming_from_outside.add(edge.target)

    node_parents = {node.id: node.parent for node in architecture.nodes}
    actor_entries = sorted(
        edge.target
        for edge in architecture.edges
        if edge.target in member_ids and node_parents.get(edge.source) is None
    )
    entry = next(
        iter(actor_entries),
        next(
            iter(sorted(incoming_from_outside)),
            next(iter(sorted(node_id for node_id, count in incoming_runtime.items() if count == 0)), None),
        ),
    )
    main_chain: list[str] = []
    current = entry
    while current and current not in main_chain:
        main_chain.append(current)
        successors = sorted(set(outgoing_runtime[current]))
        if len(successors) != 1 or incoming_runtime[successors[0]] != 1:
            break
        current = successors[0]

    cursor_x = runtime_left
    main_y = runtime_top + 58.0
    for node_id in main_chain:
        node = next(item for item in runtime_members if item.id == node_id)
        width, height = _size(node, architecture.theme)
        boxes[node.id] = Box(cursor_x, main_y, width, height)
        cursor_x += width + 120.0

    runtime_ranks = _member_ranks(architecture, member_ids)
    support_nodes = sorted(
        (node for node in runtime_members if node.id not in main_chain),
        key=lambda item: (runtime_ranks[item.id], item.id),
    )
    support_y = main_y + max((_size(node, architecture.theme)[1] for node in runtime_members), default=82.0) + 92.0
    support_x = runtime_left
    for index, node in enumerate(support_nodes):
        width, height = _size(node, architecture.theme)
        boxes[node.id] = Box(support_x, support_y, width, height)
        support_x += width + 86.0
        if (index + 1) % 3 == 0:
            support_x = runtime_left
            support_y += height + 62.0

    group_boxes: dict[str, Box] = {}
    if runtime_members:
        members = [boxes[node.id] for node in runtime_members]
        left = min(box.x for box in members) - 34.0
        top = min(box.y for box in members) - 58.0
        right = max(box.right for box in members) + 34.0
        bottom = max(box.bottom for box in members) + 34.0
        group_boxes["runtime"] = Box(left, top, right - left, bottom - top)
    else:
        group_boxes["runtime"] = Box(runtime_left, runtime_top, 420.0, 260.0)

    ungrouped = [node for node in architecture.nodes if node.parent is None]
    entry_y = min((boxes[node.id].center[1] for node in runtime_members), default=runtime_top + 100.0)
    cursor_y = max(
        110.0,
        entry_y - (sum(_size(node, architecture.theme)[1] for node in ungrouped)
                   + max(0, len(ungrouped) - 1) * 44.0) / 2,
    )
    for node in sorted(ungrouped, key=lambda item: item.id):
        width, height = _size(node, architecture.theme)
        boxes[node.id] = Box(60.0, cursor_y, width, height)
        cursor_y += height + 44.0

    # Domain capability groups sit below the deployable runtime. Their members
    # are arranged by graph rank so independent stages share a row and only
    # true downstream stages move to the next row.
    detail_groups = [
        group
        for group in architecture.groups
        if group.id not in {"runtime", "data", "integrations"}
    ]
    detail_left = runtime_left
    detail_top = group_boxes["runtime"].bottom + 76.0
    detail_cursor_x = detail_left
    detail_cursor_y = detail_top
    detail_row_height = 0.0
    detail_max_row_width = max(1600.0, group_boxes["runtime"].width + 240.0)
    for group in detail_groups:
        members = [node for node in architecture.nodes if node.parent == group.id]
        if not members:
            if detail_cursor_x > detail_left and detail_cursor_x + 300.0 > detail_left + detail_max_row_width:
                detail_cursor_x = detail_left
                detail_cursor_y += detail_row_height + 54.0
                detail_row_height = 0.0
            group_boxes[group.id] = Box(detail_cursor_x, detail_cursor_y, 300.0, 180.0)
            detail_cursor_x += 354.0
            detail_row_height = max(detail_row_height, 180.0)
            continue
        member_ids = {node.id for node in members}
        ranks = _member_ranks(architecture, member_ids)
        by_rank: dict[int, list[Node]] = defaultdict(list)
        for node in members:
            by_rank[ranks[node.id]].append(node)
        row_widths = {
            rank: sum(_size(node, architecture.theme)[0] for node in nodes)
            + max(0, len(nodes) - 1) * 54.0
            for rank, nodes in by_rank.items()
        }
        content_width = max(row_widths.values(), default=240.0)
        group_width = content_width + 68.0
        row_heights = {
            rank: max(_size(node, architecture.theme)[1] for node in nodes)
            for rank, nodes in by_rank.items()
        }
        group_height = 46.0 + sum(height + 56.0 for height in row_heights.values())
        if (
            detail_cursor_x > detail_left
            and detail_cursor_x + group_width > detail_left + detail_max_row_width
        ):
            detail_cursor_x = detail_left
            detail_cursor_y += detail_row_height + 54.0
            detail_row_height = 0.0
        cursor_y = detail_cursor_y + 58.0
        for rank in sorted(by_rank):
            row_nodes = sorted(by_rank[rank], key=lambda item: item.id)
            cursor_x = detail_cursor_x + 34.0 + (content_width - row_widths[rank]) / 2
            row_height = max(_size(node, architecture.theme)[1] for node in row_nodes)
            for node in row_nodes:
                width, height = _size(node, architecture.theme)
                boxes[node.id] = Box(cursor_x, cursor_y, width, height)
                cursor_x += width + 54.0
            cursor_y += row_height + 56.0
        group_boxes[group.id] = Box(
            detail_cursor_x,
            detail_cursor_y,
            group_width,
            group_height,
        )
        detail_cursor_x += group_width + 54.0
        detail_row_height = max(detail_row_height, group_height)

    # Leave a routing corridor between application/capability areas and side
    # boundaries so external and data connectors do not cut through nodes.
    detail_right = max(
        (group_boxes[group.id].right for group in detail_groups),
        default=group_boxes["runtime"].right,
    )
    side_left = max(group_boxes["runtime"].right, detail_right) + 220.0
    side_top = 110.0
    side_groups = [group for group in architecture.groups if group.id in {"data", "integrations"}]
    for group in side_groups:
        members = [node for node in architecture.nodes if node.parent == group.id]
        if not members:
            group_boxes[group.id] = Box(side_left, side_top, 300.0, 180.0)
            side_top += 220.0
            continue
        max_width = max(_size(node, architecture.theme)[0] for node in members)
        cursor = side_top + 58.0
        for node in sorted(members, key=lambda item: item.id):
            width, height = _size(node, architecture.theme)
            boxes[node.id] = Box(side_left + 34.0 + (max_width - width) / 2, cursor, width, height)
            cursor += height + 44.0
        group_height = cursor - side_top - 10.0
        group_boxes[group.id] = Box(side_left, side_top, max_width + 68.0, group_height)
        side_top += group_height + 54.0

    # Unknown-parent nodes are still rendered safely instead of being dropped.
    remaining = [node for node in architecture.nodes if node.id not in boxes]
    for node in remaining:
        width, height = _size(node, architecture.theme)
        boxes[node.id] = Box(side_left, side_top, width, height)
        side_top += height + 44.0

    all_boxes = list(boxes.values()) + list(group_boxes.values())
    width = max((box.right for box in all_boxes), default=800.0) + 80.0
    routing_margin = 320.0 if detail_groups and side_groups else 90.0
    height = max((box.bottom for box in all_boxes), default=500.0) + routing_margin
    return Layout(nodes=boxes, groups=group_boxes, width=width, height=height)


def compute_layout(architecture: Architecture) -> Layout:
    group_ids = {group.id for group in architecture.groups}
    if (
        architecture.direction == "LR"
        and group_ids & set(FEATURE_LANES)
        and "runtime" in group_ids
        and not any(node.position for node in architecture.nodes)
        and not any(group.position for group in architecture.groups)
    ):
        return _feature_lane_layout(architecture)
    if (
        architecture.direction == "LR"
        and any(group.id == "runtime" for group in architecture.groups)
        and not any(node.position for node in architecture.nodes)
        and not any(group.position for group in architecture.groups)
    ):
        return _grouped_lr_layout(architecture)

    margin_x, margin_y = 80.0, 110.0
    gap_x, gap_y = 140.0, 54.0
    ranks = _ranks(architecture)
    by_rank: dict[int, list[Node]] = defaultdict(list)
    for node in architecture.nodes:
        by_rank[ranks[node.id]].append(node)

    boxes: dict[str, Box] = {}
    ordered_ranks = sorted(by_rank)
    horizontal = architecture.direction in {"LR", "RL"}
    rank_sizes: dict[int, float] = {}
    for rank, nodes in by_rank.items():
        sizes = [_size(node, architecture.theme) for node in nodes]
        rank_sizes[rank] = max((size[0] if horizontal else size[1] for size in sizes), default=80.0)

    rank_coordinate: dict[int, float] = {}
    cursor = margin_x if horizontal else margin_y
    for rank in ordered_ranks:
        rank_coordinate[rank] = cursor
        cursor += rank_sizes[rank] + (gap_x if horizontal else gap_y + 70)

    for rank in ordered_ranks:
        cross_cursor = margin_y if horizontal else margin_x
        for node in sorted(by_rank[rank], key=lambda item: (item.parent or "", item.id)):
            width, height = _size(node, architecture.theme)
            if node.position:
                box = Box(
                    node.position.x,
                    node.position.y,
                    node.position.width or width,
                    node.position.height or height,
                )
            elif horizontal:
                box = Box(rank_coordinate[rank], cross_cursor, width, height)
                cross_cursor += height + gap_y
            else:
                box = Box(cross_cursor, rank_coordinate[rank], width, height)
                cross_cursor += width + 70
            boxes[node.id] = box

    # Reverse only automatically placed nodes. Explicit positions are curated canvas
    # coordinates and remain authoritative in every direction.
    if architecture.direction in {"RL", "BT"}:
        automatic = [node for node in architecture.nodes if node.position is None]
        if automatic:
            if horizontal:
                far = max(boxes[node.id].right for node in automatic) + margin_x
                for node in automatic:
                    box = boxes[node.id]
                    boxes[node.id] = Box(far - box.right, box.y, box.width, box.height)
            else:
                far = max(boxes[node.id].bottom for node in automatic) + margin_y
                for node in automatic:
                    box = boxes[node.id]
                    boxes[node.id] = Box(box.x, far - box.bottom, box.width, box.height)

    group_boxes: dict[str, Box] = {}
    for group in architecture.groups:
        members = [boxes[node.id] for node in architecture.nodes if node.parent == group.id]
        if group.position:
            default_width = 480.0
            default_height = 300.0
            group_boxes[group.id] = Box(
                group.position.x,
                group.position.y,
                group.position.width or default_width,
                group.position.height or default_height,
            )
        elif members:
            left = min(box.x for box in members) - 34
            top = min(box.y for box in members) - 58
            right = max(box.right for box in members) + 34
            bottom = max(box.bottom for box in members) + 34
            group_boxes[group.id] = Box(left, top, right - left, bottom - top)
        else:
            group_boxes[group.id] = Box(margin_x, margin_y, 360.0, 220.0)

    all_boxes = list(boxes.values()) + list(group_boxes.values())
    width = max((box.right for box in all_boxes), default=800.0) + margin_x
    height = max((box.bottom for box in all_boxes), default=500.0) + margin_y
    return Layout(nodes=boxes, groups=group_boxes, width=width, height=height)
