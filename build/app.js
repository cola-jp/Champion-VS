var q=document.getElementById('q'),cnt=document.getElementById('cnt'),
    cards=[].slice.call(document.querySelectorAll('.card')),idx=document.getElementById('idx');
function norm(s){return s.replace(/[\u3041-\u3096]/g,function(c){return String.fromCharCode(c.charCodeAt(0)+96)}).replace(/[ー・\s]/g,'')}
function render(){
  var k=norm(q.value.trim()),n=0;
  cards.forEach(function(c){var m=!k||norm(c.dataset.n).indexOf(k)>=0;c.classList.toggle('hide',!m);if(m)n++;});
  cnt.textContent=n+' / '+cards.length;
  idx.style.display=k?'none':'';
  if(k)scrollTo(0,0);
}
q.addEventListener('input',render);
var mg=true;
document.getElementById('tM').addEventListener('click',function(e){
  mg=!mg;e.currentTarget.setAttribute('aria-pressed',mg);
  [].forEach.call(document.querySelectorAll('tr.nonmega'),function(r){r.classList.toggle('hide',!mg)});
});
// ステルスロック切り替え。両方の行は既に書き出してあるので、bodyのクラスを付け替えるだけ。
// ここでダメージを計算し直さないこと（JSが動かない環境との食い違いが出る）。
var sr=false;
document.getElementById('tS').addEventListener('click',function(e){
  sr=!sr;e.currentTarget.setAttribute('aria-pressed',sr);
  document.body.classList.toggle('sron',sr);
});
addEventListener('keydown',function(e){
  if(e.key==='/'&&document.activeElement!==q){e.preventDefault();q.focus();q.select();}
  if(e.key==='Escape'){q.value='';render();}
});
document.getElementById('tools').hidden=false;
render();
