"""Run the tests in isolated processes so Qt/kernel caches do not accumulate.

  validation_runner.py --quick   a few-second smoke test (what the installers run)
  validation_runner.py           the full suite, test modules in parallel
"""
import argparse,concurrent.futures,json,os,re,subprocess,sys,time
from pathlib import Path


def run_batch(root,logs,index,group,number,timeout):
 env=os.environ.copy()
 env.update(PYTHONUTF8='1',PYTHONIOENCODING='utf-8',QT_QPA_PLATFORM='offscreen',SLOTHCAD_RENDERER='software',SLOTHCAD_RECOVERY_DIR=str(logs/f'recovery-{index}'),XDG_CONFIG_HOME=str(logs/f'config-{index}'))
 env['SLOTHCAD_CONFIG_DIR']=str(logs/f'config-{index}')  # Qt settings live in the registry on Windows otherwise
 env['PYTHONPATH']=os.pathsep.join([str(root),str(root/'tests'),env.get('PYTHONPATH','')])
 start=time.monotonic();log=logs/f'batch-{number:02d}.log'
 with log.open('w',encoding='utf-8') as stream:
  try:code=subprocess.run([sys.executable,'-m','unittest',*group,'-v'],cwd=root,env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=timeout).returncode
  except subprocess.TimeoutExpired:code=-1
 text=log.read_text(encoding='utf-8',errors='replace');count=re.search(r'Ran (\d+) tests?',text)
 passed=code==0 and bool(re.search(r'^OK(?: \(.*\))?$',text,re.M))
 print(('PASS' if passed else 'FAIL')+f' batch {number}: '+', '.join(group),flush=True)
 return dict(modules=group,tests=int(count[1]) if count else 0,passed=passed,exit_code=code,seconds=round(time.monotonic()-start,3),log=str(log))


def main():
 parser=argparse.ArgumentParser()
 parser.add_argument('--log-dir',type=Path,default=Path('.validation'))
 parser.add_argument('--group-size',type=int,default=1)
 parser.add_argument('--timeout',type=int,default=240)
 parser.add_argument('--jobs','-j',type=int,default=0,help='parallel test processes (default: half the CPU cores)')
 parser.add_argument('--quick',action='store_true',help='run only the few-second smoke test')
 args=parser.parse_args()
 root=Path(__file__).resolve().parent
 if args.quick:return subprocess.call([sys.executable,str(root/'smoke_test.py')],cwd=root)
 if args.group_size<1:parser.error('Group size must be positive.')
 jobs=args.jobs if args.jobs>0 else max(1,(os.cpu_count() or 2)//2)
 logs=args.log_dir.resolve();logs.mkdir(parents=True,exist_ok=True)
 modules=sorted(p.stem for p in (root/'tests').glob('test_*.py'))
 batches=[modules[i:i+args.group_size] for i in range(0,len(modules),args.group_size)]
 with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
  futures=[pool.submit(run_batch,root,logs,i*args.group_size,group,i+1,args.timeout) for i,group in enumerate(batches)]
  results=[future.result() for future in futures]
 report=dict(passed=all(r['passed'] for r in results),tests=sum(r['tests'] for r in results),batches=results)
 (logs/'summary.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
 print(json.dumps({'passed':report['passed'],'tests':report['tests'],'batches':len(results)}),flush=True)
 return 0 if report['passed'] else 1


if __name__=='__main__':sys.exit(main())
