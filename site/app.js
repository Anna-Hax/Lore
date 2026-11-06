/* Lore landing page — behavior
   - seeded maze generation for the cube faces
   - black "runner" lines animated through the maze corridors
   - starfield, floating mini cubes, pointer parallax */

/* ============ tiny seeded rng ============ */
function mulberry32(a){return function(){a|=0;a=a+0x6D2B79F5|0;var t=Math.imul(a^a>>>15,1|a);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296}}

/* ============ maze generation (recursive backtracker) ============ */
function carveMaze(n,rng){
  const visited=Array.from({length:n},()=>Array(n).fill(false));
  const stack=[[0,0]];visited[0][0]=true;
  const polys=[];let cur=[[0,0]];
  while(stack.length){
    const [x,y]=stack[stack.length-1];
    const nbs=[[1,0],[-1,0],[0,1],[0,-1]]
      .map(([dx,dy])=>[x+dx,y+dy])
      .filter(([a,b])=>a>=0&&a<n&&b>=0&&b<n&&!visited[b][a]);
    if(nbs.length){
      const [nx,ny]=nbs[(rng()*nbs.length)|0];
      visited[ny][nx]=true;stack.push([nx,ny]);cur.push([nx,ny]);
    }else{
      stack.pop();
      if(cur.length>1)polys.push(cur);
      cur=stack.length?[stack[stack.length-1].slice()]:[];
    }
  }
  return polys;
}
function polyToD(poly,toXY){
  return poly.map((c,i)=>(i?'L':'M')+toXY(c).join(' ')).join('');
}

/* ============ build one maze face ============ */
const SVGNS='http://www.w3.org/2000/svg';
const REDUCED=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
function buildFace(seed,faceClass){
  const SIZE=600,N=13,PAD=10;
  const rng=mulberry32(seed);
  const cell=(SIZE-PAD*2)/N;
  const toXY=([x,y])=>[+(PAD+cell/2+x*cell).toFixed(1),+(PAD+cell/2+y*cell).toFixed(1)];
  const polys=carveMaze(N,rng);
  const allD=polys.map(p=>polyToD(p,toXY)).join('');

  const svg=document.createElementNS(SVGNS,'svg');
  svg.setAttribute('viewBox',`0 0 ${SIZE} ${SIZE}`);
  svg.setAttribute('preserveAspectRatio','none');
  const uid=faceClass+seed;
  svg.innerHTML=`
    <defs>
      <radialGradient id="bg${uid}" cx="50%" cy="42%" r="75%">
        <stop offset="0%" stop-color="#4a0d07"/>
        <stop offset="55%" stop-color="#24070a"/>
        <stop offset="100%" stop-color="#0c0407"/>
      </radialGradient>
      <linearGradient id="cor${uid}" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%" stop-color="#ff5a30"/>
        <stop offset="45%" stop-color="#e52315"/>
        <stop offset="100%" stop-color="#8f0f06"/>
      </linearGradient>
      <filter id="blur${uid}" x="-20%" y="-20%" width="140%" height="140%">
        <feGaussianBlur stdDeviation="9"/>
      </filter>
    </defs>
    <rect width="${SIZE}" height="${SIZE}" fill="url(#bg${uid})"/>
    <g fill="none" stroke-linecap="round" stroke-linejoin="round">
      <path d="${allD}" stroke="#ff2e1f" stroke-width="${cell*.62}" opacity=".5" filter="url(#blur${uid})"/>
      <path d="${allD}" stroke="url(#cor${uid})" stroke-width="${cell*.46}"/>
      <path d="${allD}" stroke="#ff8a5a" stroke-width="${cell*.1}" opacity=".35"/>
      <g class="runners"></g>
    </g>
    <rect width="${SIZE}" height="${SIZE}" fill="none" stroke="rgba(0,0,0,.85)" stroke-width="6"/>
  `;

  /* ---- the internally moving black lines ---- */
  const runners=svg.querySelector('.runners');
  const rrng=mulberry32(seed^0x9e37);
  polys.forEach(poly=>{
    const path=document.createElementNS(SVGNS,'path');
    path.setAttribute('d',polyToD(poly,toXY));
    path.setAttribute('stroke','#0a0507');
    path.setAttribute('stroke-width',cell*.46);
    path.setAttribute('fill','none');
    runners.appendChild(path);
    const len=path.getTotalLength();
    const dash=Math.max(26,len*(.1+rrng()*.14));      // black segment length
    const gap=Math.max(len-dash, dash*2.2);           // spacing between segments
    path.setAttribute('stroke-dasharray',`${dash} ${gap}`);
    path.setAttribute('stroke-dashoffset',rrng()*(dash+gap));
    const speed=55+rrng()*65;                          // px per second
    const dir=rrng()<.5?1:-1;
    if(!REDUCED) path.animate(
      [{strokeDashoffset:path.getAttribute('stroke-dashoffset')},
       {strokeDashoffset:(+path.getAttribute('stroke-dashoffset'))-dir*(dash+gap)}],
      {duration:((dash+gap)/speed)*1000,iterations:Infinity,easing:'linear'}
    );
  });

  const face=document.createElement('div');
  face.className='face '+faceClass;
  face.appendChild(svg);
  const shade=document.createElement('div');
  shade.className='shade';
  face.appendChild(shade);
  return face;
}

const cube=document.getElementById('cube');
[['front',11],['right',29],['left',47],['top',83]].forEach(([cls,seed])=>{
  cube.appendChild(buildFace(seed,cls));
});

/* ============ floating mini cubes ============ */
function miniCube(size){
  const w=document.createElement('div');
  w.className='floater f-bob';
  w.style.width=size+'px';w.style.height=size+'px';
  w.style.setProperty('--bobdur',(7+Math.random()*6)+'s');
  const m=document.createElement('div');
  m.className='mini';
  m.style.setProperty('--spin',(20+Math.random()*22)+'s');
  const tf={
    front:`rotateY(0deg) translateZ(${size/2}px)`,
    back:`rotateY(180deg) translateZ(${size/2}px)`,
    right:`rotateY(90deg) translateZ(${size/2}px)`,
    left:`rotateY(-90deg) translateZ(${size/2}px)`,
    top:`rotateX(90deg) translateZ(${size/2}px)`,
    bottom:`rotateX(-90deg) translateZ(${size/2}px)`
  };
  for(const k in tf){
    const f=document.createElement('div');
    f.className='mf';f.style.transform=tf[k];
    m.appendChild(f);
  }
  w.appendChild(m);
  return w;
}
const stage=document.querySelector('.hero-stage');
[['8%','64%',54],['86%','38%',40],['78%','30%',24],['16%','26%',26]].forEach(([l,t,s])=>{
  const c=miniCube(s);
  c.style.left=l;c.style.top=t;c.style.perspective='600px';
  stage.appendChild(c);
});

/* ============ starfield ============ */
const cv=document.getElementById('stars'),cx=cv.getContext('2d');
let stars=[];
function seedStars(){
  cv.width=innerWidth;cv.height=innerHeight;
  const n=Math.min(170,(innerWidth*innerHeight)/9000|0);
  stars=Array.from({length:n},()=>({
    x:Math.random()*cv.width,y:Math.random()*cv.height,
    r:Math.random()*1.3+.3,
    p:Math.random()*Math.PI*2,
    s:.4+Math.random()*1.2,
    red:Math.random()<.18
  }));
}
seedStars();addEventListener('resize',seedStars);
(function twinkle(t){
  cx.clearRect(0,0,cv.width,cv.height);
  for(const s of stars){
    const a=.25+.55*(.5+.5*Math.sin(t/900*s.s+s.p));
    cx.beginPath();cx.arc(s.x,s.y,s.r,0,7);
    cx.fillStyle=s.red?`rgba(255,80,60,${a})`:`rgba(255,240,235,${a*.9})`;
    cx.fill();
  }
  if(!REDUCED) requestAnimationFrame(twinkle);
})(0);

/* ============ mouse parallax ============ */
const outer=document.getElementById('cubeOuter');
const tilt=document.getElementById('cubeTilt');
let tx=0,ty=0,cxv=0,cyv=0;
addEventListener('pointermove',e=>{
  tx=(e.clientX/innerWidth-.5);
  ty=(e.clientY/innerHeight-.5);
});
(function lerp(){
  cxv+=(tx-cxv)*.04;cyv+=(ty-cyv)*.04;
  tilt.style.transform=`rotateX(${-32-cyv*8}deg) rotateY(${-45+cxv*10}deg)`;
  outer.style.translate=`${(cxv*-18).toFixed(1)}px ${(cyv*-10).toFixed(1)}px`;
  if(!REDUCED) requestAnimationFrame(lerp);
})();
