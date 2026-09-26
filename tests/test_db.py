from bot.db import DB


def test_history_starts_with_user(tmp_path):
    db = DB(tmp_path / "t.db")
    db.add_history(1, "user", "a")
    db.add_history(1, "assistant", "b")
    db.add_history(1, "user", "c")
    db.add_history(1, "assistant", "d")
    assert [m["content"] for m in db.get_history(1, 3)] == ["c", "d"]  # leading assistant msg dropped


def test_notes_are_per_user(tmp_path):
    db = DB(tmp_path / "t.db")
    nid = db.add_note(1, "hello")
    assert not db.delete_note(2, nid)
    assert db.delete_note(1, nid)


def test_reminders_and_alerts(tmp_path):
    db = DB(tmp_path / "t.db")
    rid = db.add_reminder(5, "x", 123.0)
    assert len(db.pending_reminders(5)) == 1
    assert not db.finish_reminder(rid, chat_id=6)
    assert db.finish_reminder(rid, chat_id=5)
    aid = db.add_alert(5, "EURUSD", ">", 1.1)
    assert db.deactivate_alert(aid) and not db.active_alerts()


def test_verify(tmp_path):
    db = DB(tmp_path / "t.db")
    db.verify_user(10, 20, "91", "Me")
    assert db.is_verified(10) and db.owner_chat_ids() == [20]
