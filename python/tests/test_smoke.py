from learning_py import __version__, main


def test_version_is_set() -> None:
    assert isinstance(__version__, str) and __version__


def test_main_runs(capsys) -> None:
    main()
    out = capsys.readouterr().out
    assert "learning-py" in out
