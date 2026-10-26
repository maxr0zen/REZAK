"""Check the Windows PowerShell host used by the desktop queue, not pwsh."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(os.name != 'nt', reason='Windows PowerShell 5.1 host')
def test_live_script_parses_and_emits_utf8_events(tmp_path):
    root = Path(__file__).resolve().parents[1]
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    shutil.copyfile(root / 'scripts/process-live.ps1', scripts / 'process-live.ps1')
    # Stub Docker in an isolated project: never start containers or take the real lock.
    wrapper = tmp_path / 'check.ps1'
    wrapper.write_text('''
$ErrorActionPreference = 'Stop'
function global:docker { $global:LASTEXITCODE = 0 }
& (Join-Path $PSScriptRoot 'scripts/process-live.ps1') -SourceId mock_live -RequestFile mock_live.json
''', encoding='utf-8-sig')
    result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                             '-File', str(wrapper)], capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr.decode('utf-8', errors='replace')
    lines = result.stdout.decode('utf-8').splitlines()
    event = next(json.loads(line.removeprefix('[REZAK_EVENT]'))
                 for line in lines if line.startswith('[REZAK_EVENT]'))
    assert event['stage'] == 'llm' and event['progress'] is None
    assert event['message'] == 'LIVE: загрузка или подключение Bonsai; точный процент неизвестен'
    assert event['pipeline_owned'] is True
