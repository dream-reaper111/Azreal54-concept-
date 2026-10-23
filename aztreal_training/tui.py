"""Dark curses terminal manager, backed exclusively by measured/durable state."""
import curses
import json
import sys

from . import datasets,jobs,registry,resources


def snapshot():
    return {'title':'AZTREÁL / AZRAEL54 TRAINING CONTROL','models':registry.models(),
            'datasets':datasets.list_datasets(),'jobs':jobs.list_jobs(),'gpu':resources.gpus(),
            'cpu':{'available':True,'available_ram_bytes':resources.memory_available()},
            'states':['available','training','evaluating','paused','stopping','completed','failed','not implemented'],
            'production_deployment':'unchanged'}


def launch(once=False):
    if not sys.stdin.isatty() or not sys.stdout.isatty():return snapshot()
    def screen(stdscr):
        curses.curs_set(0);curses.start_color();curses.use_default_colors()
        curses.init_pair(1,curses.COLOR_CYAN,curses.COLOR_BLACK)
        stdscr.bkgd(' ',curses.color_pair(1));stdscr.timeout(1000)
        page='jobs';message='';count=0
        while True:
            data=snapshot();stdscr.erase();height,width=stdscr.getmaxyx()
            lines=[data['title'],'[1] Models [2] Datasets [3] Jobs [4] GPUs [s] Start [x] Stop [r] Resume [q] Quit',
                   f"CPU available | RAM free {data['cpu']['available_ram_bytes']/1024**3:.1f} GiB | NVIDIA telemetry {'available' if data['gpu']['available'] else 'unavailable'}",'']
            if page=='jobs':
                for j in data['jobs']:
                    lines.extend([f"{j['id']}  {j['model']}  {j['state']}  device={j['assigned_device']}",
                        f"  epoch={j['epoch']} step={j['step']} loss={j['loss']} validation={j['validation_loss']} lr={j['learning_rate']}",
                        f"  stage={j['stage']} checkpoint={j['checkpoint'] or j.get('resume_checkpoint') or 'none yet'}"])
                if not data['jobs']:lines.append('No training jobs. No progress values have been observed.')
            elif page=='models':
                for m in data['models']:lines.extend([f"{m['id']} | {m['type']} | {'available' if m['available'] else 'unavailable'}",f"  {m['training']}",f"  {m['checkpoint']}"])
            elif page=='datasets':
                for d in data['datasets']:lines.append(f"{d['id']} {d['kind']} records={d['records']} reviewed={d['approved']} splits={d['split']}")
                if not data['datasets']:lines.append('Import and explicitly review a local dataset using datasets import.')
            else:lines+=json.dumps(data['gpu'],indent=2).splitlines()
            lines+=['',message,'Candidates are isolated. Training completion never deploys production weights.']
            for i,line in enumerate(lines[:max(0,height-1)]):
                if width>2:stdscr.addnstr(i,0,line,max(1,width-1))
            stdscr.refresh();count+=1
            if once and count>=1:return
            key=stdscr.getch()
            if key in (ord('q'),27):return
            if key in (ord('1'),ord('2'),ord('3'),ord('4')):page={'1':'models','2':'datasets','3':'jobs','4':'gpu'}[chr(key)]
            if key in (ord('x'),ord('r')):
                try:
                    selected=next(j for j in data['jobs'] if j['state'] in (jobs.ACTIVE if key==ord('x') else {'paused'}))
                    result=jobs.stop(selected['id']) if key==ord('x') else jobs.resume(selected['id'])
                    message=result['id']+' '+result['state']
                except StopIteration:message='No eligible active/paused job'
                except Exception as e:message=str(e)[:300]
            if key==ord('s'):
                curses.echo();curses.curs_set(1)
                try:
                    prompts=[('model','Model ID: '),('dataset','Admitted dataset version: '),('backend','Backend [podman/local/docker]: ')]
                    values={}
                    for field,prompt in prompts:
                        stdscr.erase();stdscr.addstr(0,0,prompt);stdscr.refresh();values[field]=stdscr.getstr(1,0,100).decode('utf-8')
                    result=jobs.start({'model':values['model'],'backend':values['backend'] or 'podman','epochs':2},values['dataset'])
                    message='Started '+result['id'];page='jobs'
                except Exception as e:message=str(e)[:300]
                finally:curses.noecho();curses.curs_set(0)
    try:curses.wrapper(screen)
    except curses.error as e:raise ValueError('Interactive terminal unavailable; set a valid TERM or use training status: '+str(e)) from None
    return None
