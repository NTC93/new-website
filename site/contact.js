(()=>{
 const form=document.querySelector('#ntc-contact-form');if(!form)return;
 const status=document.querySelector('#contact-status'),button=form.querySelector('button[type=submit]');
 const show=(message,error=false)=>{status.textContent=message;status.className='contact-status'+(error?' error':'');};
 async function token(){
  const r=await fetch('/contact-api.php',{cache:'no-store',credentials:'same-origin'}),d=await r.json();
  if(!r.ok||!d.ok||!d.token)throw Error('not available');form.elements.token.value=d.token;
 }
 const route=new URLSearchParams(location.search).get('bereich');
 if(route&&[...form.elements.route.options].some(o=>o.value===route))form.elements.route.value=route;
 async function init(){button.disabled=true;try{await token();button.disabled=false;show('')}catch{show('Das Kontaktformular ist momentan nicht verfügbar. Bitte versuche es später erneut.',true)}}
 form.addEventListener('submit',async e=>{
  e.preventDefault();if(button.disabled||!form.reportValidity())return;
  button.disabled=true;show('Nachricht wird versendet …');
  try{
   const r=await fetch('/contact-api.php',{method:'POST',credentials:'same-origin',body:new FormData(form),cache:'no-store'});
   const d=await r.json();
   if(r.ok&&d.ok){form.reset();show(d.message);try{await token();button.disabled=false}catch{};return}
   show(d.message||'Die Nachricht konnte nicht versendet werden.',true);
   if(r.status===403){await token();show('Bitte sende die Nachricht erneut.',true)}
  }catch{show('Die Übermittlung konnte nicht bestätigt werden. Bitte versuche es später erneut.',true)}
  button.disabled=false;
 });
 init();
})();
