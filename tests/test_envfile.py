"""Загрузка .env в окружение процесса: значения из файла не перетирают существующие."""
import os

from rezak.envfile import load_env_file


def test_load_env_file_sets_missing_keys(tmp_path, monkeypatch):
    monkeypatch.delenv('REZAK_TEST_ONE', raising=False)
    monkeypatch.delenv('REZAK_TEST_TWO', raising=False)
    file = tmp_path/'.env'
    file.write_text('# comment\nREZAK_TEST_ONE=first\nREZAK_TEST_TWO="second value"\n', encoding='utf-8')
    applied = load_env_file(file)
    assert 'REZAK_TEST_ONE' in applied
    assert os.environ['REZAK_TEST_ONE'] == 'first'
    assert os.environ['REZAK_TEST_TWO'] == 'second value'


def test_load_env_file_keeps_existing_environment(tmp_path, monkeypatch):
    monkeypatch.setenv('REZAK_TEST_KEEP', 'from-environment')
    file = tmp_path/'.env'
    file.write_text('REZAK_TEST_KEEP=from-file\n', encoding='utf-8')
    applied = load_env_file(file)
    assert 'REZAK_TEST_KEEP' not in applied
    assert os.environ['REZAK_TEST_KEEP'] == 'from-environment'


def test_load_env_file_without_file(tmp_path):
    assert load_env_file(tmp_path/'missing.env') == []
