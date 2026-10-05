/* Shared dashboard/login theme. No server access is needed to restore a colour. */
(()=>{
const $=selector=>document.querySelector(selector);
function el(tag,text){const node=document.createElement(tag);if(text!==undefined)node.textContent=text;return node}
const colourPresets=[['Tmavomodrá','#000f5c'],['Šalvia','#a8bd91'],['Modrá','#92b8ce'],['Levanduľa','#b5a4cc'],['Ružová','#cf9faa'],['Piesková','#cbb592'],['Tyrkysová','#8dbeb4']];
const mixColour=(a,b,p)=>a.map((v,i)=>Math.round(v*(1-p)+b[i]*p));
const colourCSS=c=>'#'+c.map(v=>v.toString(16).padStart(2,'0')).join('');
function luminance(rgb){const c=rgb.map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4});return .2126*c[0]+.7152*c[1]+.0722*c[2]}
function contrast(a,b){const x=luminance(a),y=luminance(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05)}
function applyColour(hex,persist=true){if(!/^#[0-9a-f]{6}$/i.test(hex))return;hex=hex.toLowerCase();const rgb=[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16)),dark=[17,24,32],white=[255,255,255],panel=[26,34,44];const ink=contrast(rgb,dark)>=contrast(rgb,white)?dark:white;let readable=rgb;for(let i=1;contrast(readable,panel)<4.5&&i<=20;i++)readable=mixColour(rgb,white,i/20);const vars={'--lime':hex,'--accent-ink':colourCSS(ink),'--accent-ui':colourCSS(readable),'--accent-tint':colourCSS(mixColour(panel,rgb,.18)),'--accent-field':colourCSS(mixColour(rgb,ink,.06)),'--accent-border':colourCSS(mixColour(rgb,ink,.32))};for(const [name,value]of Object.entries(vars))document.documentElement.style.setProperty(name,value);if($('#custom-colour'))$('#custom-colour').value=hex;document.querySelectorAll('#colour-presets button').forEach(b=>b.setAttribute('aria-pressed',b.dataset.colour===hex));if(persist)try{localStorage.setItem('zssk-accent',hex)}catch{}}
function openPalette(){$('#palette-dialog').showModal()}

window.applyColour=applyColour;
window.openPalette=openPalette;
let savedColour='#000f5c';
try{savedColour=localStorage.getItem('zssk-accent')||savedColour}catch{}
if(!/^#[0-9a-f]{6}$/i.test(savedColour))savedColour='#000f5c';
applyColour(savedColour,false);
function initPalette(){if(!$('#colour-presets'))return;
$('#colour-presets').replaceChildren(...colourPresets.map(([name,hex])=>{const b=el('button');b.type='button';b.dataset.colour=hex;b.style.setProperty('--swatch',hex);b.setAttribute('aria-label',name);b.title=name;b.onclick=()=>applyColour(hex);return b}));
$('#custom-colour').oninput=e=>applyColour(e.target.value);
applyColour(document.documentElement.style.getPropertyValue('--lime'),false);
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',initPalette);else initPalette();
})();
