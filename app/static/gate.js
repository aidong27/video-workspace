/* 字幕工作台 · gate: activation-code entry over a WebGL aurora. */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
  const CODE_LENGTH = 20;
  const RING = 213.63;
  const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const vault = $("vault");
  const form = $("gate-form");
  const input = $("code");
  const button = $("unlock");
  const label = $("unlock-label");
  const message = $("gate-message");
  const ring = $("lock-progress");
  const lock = $("lock");
  const warp = $("warp");
  const cells = Array.from(document.querySelectorAll(".code-cells i"));

  const sky = { energy: 0, energyTarget: 0, alert: 0, open: 0, openTarget: 0 };
  let busy = false;
  let opened = false;
  let lockTimer = null;

  /* ---------- Sky shader ---------- */

  const VERTEX = "attribute vec2 a;void main(){gl_Position=vec4(a,0.,1.);}";
  const FRAGMENT = `
precision mediump float;
uniform vec2 u_res;
uniform float u_time;
uniform vec2 u_mouse;
uniform float u_energy;
uniform float u_alert;
uniform float u_open;

float hash(vec2 p){p=fract(p*vec2(123.34,456.21));p+=dot(p,p+45.32);return fract(p.x*p.y);}
float noise(vec2 p){vec2 i=floor(p),f=fract(p);vec2 u=f*f*(3.-2.*f);
  return mix(mix(hash(i),hash(i+vec2(1.,0.)),u.x),mix(hash(i+vec2(0.,1.)),hash(i+vec2(1.,1.)),u.x),u.y);}
float fbm(vec2 p){float v=0.,a=.5;mat2 m=mat2(1.6,1.2,-1.2,1.6);
  for(int i=0;i<5;i++){v+=a*noise(p);p=m*p;a*=.5;}return v;}

void main(){
  vec2 uv=gl_FragCoord.xy/u_res;
  vec2 p=(gl_FragCoord.xy-.5*u_res)/min(u_res.x,u_res.y);
  float t=u_time*(.045+.09*u_energy);
  p+=u_mouse*.05;
  vec2 q=vec2(fbm(p*1.4+vec2(0.,t)),fbm(p*1.4+vec2(5.2,-t*.8)));
  vec2 r=vec2(fbm(p*1.6+3.*q+vec2(1.7,9.2)+t*1.3),fbm(p*1.6+3.*q+vec2(8.3,2.8)-t));
  float f=fbm(p*1.15+2.6*r);
  vec3 violet=vec3(.486,.361,1.);
  vec3 magenta=vec3(.886,.333,1.);
  vec3 cyan=vec3(.22,.88,1.);
  vec3 col=vec3(.027,.024,.051);
  col=mix(col,violet*.85,smoothstep(.24,.86,f));
  col=mix(col,magenta*.8,smoothstep(.46,1.,length(q))*.7);
  col=mix(col,cyan*.72,smoothstep(.52,1.04,r.x)*.62);
  float band=smoothstep(.026,0.,abs(f-.6-.05*sin(u_time*.27)));
  col+=band*mix(cyan,magenta,uv.x)*(.35+.6*u_energy);
  col+=pow(max(0.,f-.55),2.)*vec3(.5,.42,1.)*.9;
  col=mix(col,vec3(1.,.2,.35)*(.3+f*.7),u_alert*.5);
  col+=u_open*vec3(.62,.56,1.)*max(0.,1.-length(p)*.7);
  col*=smoothstep(1.6,.15,length(p));
  gl_FragColor=vec4(col,1.);
}`;

  function startSky() {
    const canvas = $("gate-sky");
    const gl = canvas.getContext("webgl", { antialias: false, alpha: false, depth: false, powerPreference: "low-power" });
    if (!gl) return false;
    const compile = (type, source) => {
      const shader = gl.createShader(type);
      gl.shaderSource(shader, source);
      gl.compileShader(shader);
      return gl.getShaderParameter(shader, gl.COMPILE_STATUS) ? shader : null;
    };
    const vertex = compile(gl.VERTEX_SHADER, VERTEX);
    const fragment = compile(gl.FRAGMENT_SHADER, FRAGMENT);
    if (!vertex || !fragment) return false;
    const program = gl.createProgram();
    gl.attachShader(program, vertex);
    gl.attachShader(program, fragment);
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return false;
    gl.useProgram(program);
    const buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    const position = gl.getAttribLocation(program, "a");
    gl.enableVertexAttribArray(position);
    gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);
    const uniform = (name) => gl.getUniformLocation(program, name);
    const u = {
      res: uniform("u_res"), time: uniform("u_time"), mouse: uniform("u_mouse"),
      energy: uniform("u_energy"), alert: uniform("u_alert"), open: uniform("u_open")
    };
    const mouse = { x: 0, y: 0, tx: 0, ty: 0 };
    window.addEventListener("pointermove", (event) => {
      mouse.tx = (event.clientX / window.innerWidth) * 2 - 1;
      mouse.ty = -((event.clientY / window.innerHeight) * 2 - 1);
    }, { passive: true });

    function resize() {
      const scale = window.innerWidth < 720 ? 0.42 : 0.6;
      canvas.width = Math.max(2, Math.round(window.innerWidth * scale));
      canvas.height = Math.max(2, Math.round(window.innerHeight * scale));
      gl.viewport(0, 0, canvas.width, canvas.height);
    }
    resize();
    window.addEventListener("resize", resize);

    const born = performance.now();
    function draw(now) {
      const time = calm ? 18 : (now - born) / 1000 + 18;
      sky.energy += (sky.energyTarget - sky.energy) * 0.06;
      sky.alert *= 0.94;
      sky.open += (sky.openTarget - sky.open) * 0.08;
      mouse.x += (mouse.tx - mouse.x) * 0.04;
      mouse.y += (mouse.ty - mouse.y) * 0.04;
      gl.uniform2f(u.res, canvas.width, canvas.height);
      gl.uniform1f(u.time, time);
      gl.uniform2f(u.mouse, mouse.x, mouse.y);
      gl.uniform1f(u.energy, sky.energy);
      gl.uniform1f(u.alert, sky.alert);
      gl.uniform1f(u.open, sky.open);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    }
    function loop(now) {
      if (!document.hidden) draw(now);
      requestAnimationFrame(loop);
    }
    if (calm) {
      draw(performance.now());
      window.addEventListener("resize", () => draw(performance.now()));
    } else {
      requestAnimationFrame(loop);
    }
    canvas.classList.add("live");
    return true;
  }

  try {
    if (!startSky()) document.documentElement.classList.add("no-webgl");
  } catch (_) {
    document.documentElement.classList.add("no-webgl");
  }

  /* ---------- Code entry ---------- */

  function clean(value) {
    return String(value || "")
      .toUpperCase()
      .replace(/O/g, "0")
      .replace(/[IL]/g, "1")
      .split("")
      .filter((char) => ALPHABET.includes(char))
      .join("")
      .slice(0, CODE_LENGTH);
  }

  function grouped(raw) {
    return raw.replace(/(.{5})(?=.)/g, "$1-");
  }

  function setMessage(text, tone) {
    message.textContent = text || "";
    message.className = `gate-message${tone ? ` ${tone}` : ""}`;
  }

  function sync() {
    const before = input.value;
    const caret = input.selectionStart === null ? before.length : input.selectionStart;
    const typedBeforeCaret = clean(before.slice(0, caret)).length;
    const raw = clean(before);
    const formatted = grouped(raw);
    if (formatted !== before) {
      input.value = formatted;
      const position = typedBeforeCaret + Math.floor(Math.max(0, typedBeforeCaret - 1) / 5);
      if (document.activeElement === input) input.setSelectionRange(position, position);
    }
    const count = raw.length;
    cells.forEach((cell, index) => {
      cell.style.setProperty("--fill", String(Math.min(1, Math.max(0, (count - index * 5) / 5))));
    });
    if (!lockTimer) ring.style.strokeDashoffset = String(RING * (1 - count / CODE_LENGTH));
    vault.classList.toggle("ready", count === CODE_LENGTH);
    button.disabled = count !== CODE_LENGTH || busy || Boolean(lockTimer);
    sky.energyTarget = (count / CODE_LENGTH) * 0.6;
    return raw;
  }

  function formatClock(seconds) {
    const value = Math.max(0, Math.ceil(seconds));
    if (value >= 3600) return `${Math.floor(value / 3600)} 小时 ${Math.ceil((value % 3600) / 60)} 分`;
    return `${String(Math.floor(value / 60)).padStart(2, "0")}:${String(value % 60).padStart(2, "0")}`;
  }

  function startLockout(seconds, text) {
    const total = Math.max(1, Number(seconds) || 60);
    const until = Date.now() + total * 1000;
    vault.classList.add("locked");
    input.disabled = true;
    button.disabled = true;
    clearInterval(lockTimer);
    const tick = () => {
      const left = (until - Date.now()) / 1000;
      if (left <= 0) {
        clearInterval(lockTimer);
        lockTimer = null;
        vault.classList.remove("locked", "error");
        input.disabled = false;
        setMessage("可以重新输入了。", "");
        sync();
        input.focus();
        return;
      }
      ring.style.strokeDashoffset = String(RING * (1 - left / total));
      setMessage(`${text || "尝试次数过多，已暂时锁定。"} 剩余 ${formatClock(left)}`, "error");
    };
    lockTimer = setInterval(tick, 1000);
    tick();
  }

  function shake() {
    vault.classList.remove("shake");
    void vault.offsetWidth;
    vault.classList.add("shake", "error");
    sky.alert = 1;
  }

  function fail(status, detail) {
    shake();
    if (status === 429 && Number(detail.retry_after) > 0) {
      startLockout(Number(detail.retry_after), "尝试次数过多，这个网络已被暂时锁定。");
      return;
    }
    let text = detail.message || (status ? "验证失败，请稍后重试。" : "网络连接失败，请检查网络后重试。");
    const left = Number(detail.attempts_left);
    if (Number.isFinite(left) && left <= 3) text += left > 0 ? ` 还可以再试 ${left} 次。` : "";
    setMessage(text, "error");
    input.focus();
    input.select();
  }

  function unlock(user) {
    opened = true;
    vault.classList.remove("checking", "error");
    vault.classList.add("open");
    ring.style.strokeDashoffset = "0";
    sky.openTarget = 1;
    setMessage(`欢迎，${(user && user.label) || "朋友"}。正在进入工作台…`, "ok");
    const rect = lock.getBoundingClientRect();
    warp.style.setProperty("--x", `${Math.round(rect.left + rect.width / 2)}px`);
    warp.style.setProperty("--y", `${Math.round(rect.top + rect.height / 2)}px`);
    setTimeout(() => warp.classList.add("go"), calm ? 0 : 380);
    setTimeout(() => window.location.replace("/"), calm ? 150 : 1250);
  }

  async function submit() {
    const raw = clean(input.value);
    if (raw.length !== CODE_LENGTH || busy || lockTimer || opened) return;
    busy = true;
    vault.classList.remove("error");
    vault.classList.add("checking");
    button.disabled = true;
    label.textContent = "验证中";
    setMessage("", "");
    sky.energyTarget = 1;
    try {
      const response = await fetch("/api/auth/activate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        cache: "no-store",
        body: JSON.stringify({ code: grouped(raw) })
      });
      const data = await response.json().catch(() => ({}));
      if (response.ok) {
        unlock(data.user);
        return;
      }
      fail(response.status, (data && typeof data.detail === "object" && data.detail) || {});
    } catch (_) {
      fail(0, {});
    } finally {
      if (!opened) {
        busy = false;
        vault.classList.remove("checking");
        label.textContent = "解锁";
        sync();
      }
    }
  }

  input.addEventListener("input", () => {
    if (message.classList.contains("error") && !lockTimer) setMessage("", "");
    vault.classList.remove("error");
    sync();
  });
  input.addEventListener("paste", () => {
    setTimeout(() => {
      if (sync().length === CODE_LENGTH) submit();
    }, 0);
  });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    submit();
  });

  sync();
  requestAnimationFrame(() => input.focus({ preventScroll: true }));
})();
