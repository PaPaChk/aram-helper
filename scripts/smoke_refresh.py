import json, os, subprocess, sys
from pathlib import Path
root=Path(__file__).resolve().parent.parent
home=root.parent / '.cache' / 'aramhex-tw-final-smoke'
env=os.environ.copy()
env['ARAMHEX_HOME']=str(home)
env['PYTHONIOENCODING']='utf-8'
r=subprocess.run([sys.executable,'-m','lolhex','--refresh'],cwd=root,env=env,capture_output=True,text=True,encoding='utf-8',timeout=300)
print(json.dumps({'code':r.returncode,'stdout':r.stdout[-4000:],'stderr':r.stderr[-2000:]},ensure_ascii=False))
