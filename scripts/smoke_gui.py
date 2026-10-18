import json, os, subprocess, sys
from pathlib import Path
root=Path(__file__).resolve().parent.parent
home=root.parent/'.cache'/'aramhex-tw-gui-smoke'
home.mkdir(parents=True, exist_ok=True)
report=home/'report.json'
env=os.environ.copy(); env['ARAMHEX_HOME']=str(home); env['QT_QPA_PLATFORM']='offscreen'; env['PYTHONIOENCODING']='utf-8'
r=subprocess.run([sys.executable,'-m','lolhex','--self-test-gui',str(report)],cwd=root,env=env,capture_output=True,text=True,encoding='utf-8',timeout=120)
data=json.loads(report.read_text(encoding='utf-8')) if report.exists() else None
print(json.dumps({'code':r.returncode,'stdout':r.stdout,'stderr':r.stderr[-2000:],'report':data},ensure_ascii=False))
