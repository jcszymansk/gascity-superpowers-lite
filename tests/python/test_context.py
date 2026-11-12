from pathlib import Path

import pytest

from litetools.context import CardRef, Layout, card_ref
from litetools.gc import Bead
from litetools.result import Err, Ok


def bead(bead_id: str, **metadata: str) -> Bead:
    return Bead(bead_id, "open", "t", "", "", metadata)


def test_an_anchor_without_lite_cards_has_one_legacy_card() -> None:
    assert card_ref(bead("st-1"), bead("s-1")) == Ok(CardRef(1, 1, True))


def test_the_anchor_names_the_current_card() -> None:
    anchor = bead("st-1", **{"lite.cards": "3", "lite.card": "2"})
    assert card_ref(anchor, bead("s-1")) == Ok(CardRef(2, 3, False))


def test_a_pinned_step_keeps_its_card_after_the_anchor_moves_on() -> None:
    anchor = bead("st-1", **{"lite.cards": "3", "lite.card": "3"})
    assert card_ref(anchor, bead("s-1", **{"lite.card": "2"})) == Ok(CardRef(2, 3, False))


@pytest.mark.parametrize(
    ("cards", "current", "pinned"),
    [("0", "1", ""), ("x", "1", ""), ("2", "", ""), ("2", "3", ""), ("2", "0", ""), ("2", "1", "5"), ("2", "a", "")],
)
def test_invalid_card_metadata_is_refused(cards: str, current: str, pinned: str) -> None:
    anchor = bead("st-1", **{"lite.cards": cards, "lite.card": current})
    step = bead("s-1", **({"lite.card": pinned} if pinned else {}))
    assert isinstance(card_ref(anchor, step), Err)


@pytest.mark.parametrize(
    ("ref", "prefix", "last"),
    [
        (CardRef(1, 1, True), "lite.", True),
        (CardRef(1, 1, False), "lite.", True),
        (CardRef(1, 2, False), "lite.card.1.", False),
        (CardRef(2, 2, False), "lite.card.2.", True),
    ],
)
def test_one_card_keeps_the_plain_keys_and_split_cards_get_their_own(ref: CardRef, prefix: str, last: bool) -> None:
    assert ref.prefix == prefix
    assert ref.is_last is last


def test_layout_puts_numbered_cards_apart_and_a_legacy_card_at_the_root() -> None:
    layout = Layout(Path("/a/st-1"))
    assert layout.draft(2) == Path("/a/st-1/drafts/2.md")
    assert layout.card(CardRef(2, 3, False)).card == Path("/a/st-1/cards/2/card.md")
    assert layout.card(CardRef(1, 1, True)).card == Path("/a/st-1/card.md")
    assert layout.card(CardRef(1, 1, True)).root == Path("/a/st-1")
