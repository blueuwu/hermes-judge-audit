from hjr.preflight import utf8_problems


def test_utf8_mode_on_passes():
    assert utf8_problems(1, "utf-8") == []
    assert utf8_problems(1, "UTF-8") == []


def test_utf8_mode_off_fails():
    assert len(utf8_problems(0, "utf-8")) == 1


def test_code_page_fails():
    assert len(utf8_problems(1, "cp1252")) == 1
    assert len(utf8_problems(0, "cp1252")) == 2
