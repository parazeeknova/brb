"""Unit tests for stream message schemas (pure, no I/O)."""

from src.pipeline import model


def test_discover_fields_shape() -> None:
    assert model.discover_fields("https://x/y", "hv") == {"url": "https://x/y", "source": "hv"}


def test_raw_fields_shape() -> None:
    assert model.raw_fields("h", "https://x", "s") == {
        "url_hash": "h",
        "url": "https://x",
        "source": "s",
    }


def test_gated_and_embed_fields_shape() -> None:
    assert model.gated_fields("c") == {"canonical_id": "c"}
    assert model.embed_fields("h") == {"url_hash": "h"}


def test_valid_url_rejects_garbage() -> None:
    assert model.valid_url("https://boards.greenhouse.io/acme/1")
    assert not model.valid_url("")
    assert not model.valid_url("ftp://x")
    assert not model.valid_url("https://" + "a" * 2000)
