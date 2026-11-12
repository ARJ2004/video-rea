"""Synthesized sound effects, voice effects and a drone bed (ffmpeg only). The platform has no sound-effects library or
music generator; these are the closest fallback for briefs that ask for knocks, rain, static, heartbeat etc.
Storyboard use:
  clip  "ambience": "storm" | "rain" | "room"      plays under the whole clip
  clip  "music": "drone"                           low suspense drone under the whole clip (stand-in for a music bed)
  shot  "sfx": [{"type": "knock", "at": 1.0, "count": 2, "gap": 1.3}, {"type": "static", "at": 0, "dur": 1.2}, ...]
        types: knock, static, thunder, heartbeat (dur), impact, creak, silence (no-op marker)
  line  "fx": "radio" | "stranger"                 radio band-limited distortion; stranger = same voice, lower + echo"""
import subprocess
from pathlib import Path

SR = 48000


def sh(*a):
    subprocess.run([str(x) for x in a], check=True, capture_output=True)


def lavfi(expr, sec, out, af=""):
    args = ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", expr, "-t", f"{sec:.3f}"]
    if af:
        args += ["-af", af]
    sh(*args, "-ar", str(SR), "-ac", "2", str(out)); return out


def knock(out):          # wooden knock: low body thump + short click
    return lavfi(f"aevalsrc='0.9*sin(2*PI*95*t)*exp(-28*t)+0.35*sin(2*PI*210*t)*exp(-45*t)+0.25*(random(0)*2-1)*exp(-90*t)':s={SR}",
                 0.35, out, "lowpass=f=1800,volume=1.6")


def static(sec, out):
    return lavfi(f"anoisesrc=color=white:sample_rate={SR}:amplitude=0.5", sec, out,
                 "highpass=f=900,lowpass=f=4200,tremolo=f=11:d=0.6,volume=0.35")


def thunder(out):
    return lavfi(f"anoisesrc=color=brown:sample_rate={SR}:amplitude=0.9", 3.2, out,
                 "lowpass=f=260,afade=t=in:d=0.25,afade=t=out:st=0.6:d=2.6,volume=2.2")


def heartbeat(sec, out):  # lub-dub every 0.85 s
    return lavfi(f"aevalsrc='0.9*sin(2*PI*55*t)*exp(-30*mod(t,0.85))+0.7*sin(2*PI*50*t)*exp(-30*mod(t-0.22,0.85))*gte(mod(t,0.85),0.22)':s={SR}",
                 sec, out, "lowpass=f=160,volume=2.0")


def impact(out):
    return lavfi(f"aevalsrc='sin(2*PI*42*t)*exp(-3.5*t)+0.4*(random(0)*2-1)*exp(-12*t)':s={SR}", 2.5, out, "lowpass=f=300,volume=1.8")


def creak(out):
    return lavfi(f"aevalsrc='0.4*sin(2*PI*(180+60*sin(2*PI*3*t))*t)*(1-exp(-8*t))*exp(-1.5*t)':s={SR}", 1.2, out, "bandpass=f=420:w=300,volume=1.2")


def ambience(kind, sec, out):
    if kind in ("storm", "rain"):
        return lavfi(f"anoisesrc=color=pink:sample_rate={SR}:amplitude=0.6", sec, out,
                     "highpass=f=350,lowpass=f=7000,volume=" + ("0.22" if kind == "storm" else "0.15"))
    return lavfi(f"anoisesrc=color=brown:sample_rate={SR}:amplitude=0.4", sec, out, "lowpass=f=180,volume=0.12")   # room tone


def drone(sec, out):
    return lavfi(f"aevalsrc='0.20*sin(2*PI*55*t)+0.12*sin(2*PI*82.4*t+0.6*sin(2*PI*0.07*t))+0.06*sin(2*PI*110*t)':s={SR}", sec, out,
                 f"lowpass=f=400,afade=t=in:d=2,afade=t=out:st={max(0, sec - 2):.2f}:d=2,volume=0.55")


def sfx_tracks(shot, t0, work):
    """[(wav, start_s)] for a shot's "sfx" list (times relative to the shot start)."""
    out, w = [], Path(work)
    for i, e in enumerate(shot.get("sfx", [])):
        kind, at = e.get("type"), t0 + float(e.get("at", 0))
        f = w / f"sfx_{shot['id']}_{i}.wav"
        if kind == "knock":
            k = knock(f)
            for n in range(int(e.get("count", 1))):
                out.append((k, at + n * float(e.get("gap", 1.2))))
        elif kind == "static":
            out.append((static(float(e.get("dur", 1.2)), f), at))
        elif kind == "thunder":
            out.append((thunder(f), at))
        elif kind == "heartbeat":
            out.append((heartbeat(float(e.get("dur", 4)), f), at))
        elif kind == "impact":
            out.append((impact(f), at))
        elif kind == "creak":
            out.append((creak(f), at))
    return out


def voice_fx(src, fx, out):
    """radio: telephone band + mild crush + static bed; stranger: same voice slightly lower with a cold echo."""
    if fx == "radio":
        af = "highpass=f=320,lowpass=f=3200,acrusher=bits=10:mode=log:aa=1:mix=0.35,volume=1.4"
    elif fx == "stranger":
        rate = int(subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=sample_rate",
                                            "-of", "csv=p=0", str(src)]).decode().strip() or 44100)
        af = f"asetrate={int(rate * 0.93)},aresample={rate},aecho=0.7:0.5:70|140:0.35|0.2,volume=1.1"
    else:
        return src
    sh("ffmpeg", "-loglevel", "error", "-y", "-i", str(src), "-af", af, str(out)); return out
