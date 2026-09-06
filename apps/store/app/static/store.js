(()=>{
  const $=(s,r=document)=>r.querySelector(s), $$=(s,r=document)=>Array.from(r.querySelectorAll(s));
  const escapeHtml=(s)=>String(s??'').replace(/[&<>'"]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[m]));
  const rupiah=n=>'Rp'+Number(n||0).toLocaleString('id-ID');
  const paymentLabel=s=>({pending:'Menunggu Pembayaran',paid:'Lunas',failed:'Gagal',cancelled:'Dibatalkan',expired:'Kedaluwarsa',refunded:'Dikembalikan'}[s]||s);
  const licenseLabel=s=>({pending:'Menunggu',issuing:'Diproses',issued:'Kode Siap'}[s]||s);
  const api=async(url,opt={})=>{const r=await fetch(url,{credentials:'same-origin',...opt});let d={};try{d=await r.json()}catch{}if(!r.ok){const e=new Error(d.detail||`HTTP ${r.status}`);e.status=r.status;throw e}return d};

  const choose=$('#chooseApp'); if(choose) choose.addEventListener('click',e=>{e.preventDefault();$('#top-products')?.scrollIntoView({behavior:'smooth'});});

  const modal=$('#checkoutModal'), form=$('#checkoutForm');
  if(modal&&form){
    const close=()=>{modal.classList.remove('open');modal.setAttribute('aria-hidden','true');document.body.style.overflow=''};
    const open=(b)=>{
      const type=b.dataset.type, edition=b.dataset.edition;
      form.elements.edition.value=edition; form.elements.license_type.value=type;
      $('#summaryType').textContent=type==='trial'?'Uji Coba 3 Hari':type==='upgrade'?'Peningkatan Paket':'Lisensi Penuh';
      $('#summaryEdition').textContent=type==='trial'?'Paket uji coba':edition==='Essential'?'Dasar':edition==='Professional'?'Profesional':edition==='Multi Outlet'?'Multi Lokasi':edition;
      $('#checkoutSub').textContent=type==='upgrade'?'Masukkan ID perangkat yang sudah memiliki lisensi. Paket aktif akan diperiksa otomatis.':type==='trial'?'Uji coba berlaku satu kali untuk setiap aplikasi dan perangkat.':'Lengkapi data untuk membuat pesanan.';
      $('#formError').textContent=''; modal.classList.add('open');modal.setAttribute('aria-hidden','false');document.body.style.overflow='hidden';
      setTimeout(()=>form.elements.customer?.focus(),80);
    };
    $$('.js-checkout').forEach(b=>b.addEventListener('click',()=>open(b))); $$('.js-close').forEach(b=>b.addEventListener('click',close));
    document.addEventListener('keydown',e=>{if(e.key==='Escape'&&modal.classList.contains('open'))close()});
    form.addEventListener('submit',async e=>{
      e.preventDefault(); const btn=$('.submit-order',form), err=$('#formError'); err.textContent='';btn.disabled=true;btn.textContent='Memproses...';
      const fd=new FormData(form); const body=Object.fromEntries(fd.entries()); body.device=String(body.device||'').trim().toUpperCase();
      try{const d=await api('/store/api/order',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}); if(d.payment_url) location.href=d.payment_url; else location.href=d.status_url;}
      catch(ex){err.textContent=ex.message;btn.disabled=false;btn.textContent='Lanjutkan';}
    });
  }

  const orderRoot=$('#orderRoot');
  if(orderRoot){
    const orderId=orderRoot.dataset.orderId;
    const refresh=async()=>{try{const d=await api(`/store/order/${encodeURIComponent(orderId)}/status`);const pp=$('#statusPill');pp.textContent=paymentLabel(d.payment_status);pp.className=`status-pill ${d.payment_status}`;$('#paymentState').textContent=paymentLabel(d.payment_status);$('#licenseState').textContent=licenseLabel(d.fulfillment_status);$('#paymentBox').classList.toggle('done',d.payment_status==='paid');$('#licenseBox').classList.toggle('done',d.fulfillment_status==='issued');const ta=$('#tokenArea');if(d.license_token){$('#licenseToken').textContent=d.license_token;ta.classList.remove('hidden')}if(d.payment_url&&d.payment_status==='pending'){let p=$('#payButton');if(!p){p=document.createElement('a');p.id='payButton';p.className='btn primary';p.textContent='Bayar Sekarang';$('#paymentBox').appendChild(p)}p.href=d.payment_url}else $('#payButton')?.remove();}catch(e){console.warn(e)}};
    $('#refreshOrder')?.addEventListener('click',refresh);$('#copyToken')?.addEventListener('click',async()=>{const t=$('#licenseToken')?.textContent||'';if(!t)return;try{await navigator.clipboard.writeText(t);$('#copyToken').textContent='Tersalin';setTimeout(()=>$('#copyToken').textContent='Salin',1200)}catch{}});
    setInterval(refresh,12000);
  }

  const adminLogin=$('#adminLogin'), content=$('#adminContent');
  if(adminLogin&&content){
    const loginErr=$('#adminLoginError');
    const showAdmin=()=>{adminLogin.classList.add('hidden');content.classList.remove('hidden');loadOrders();loadPrices()};
    const loadOrders=async()=>{try{const a=await api('/store/api/admin/orders');showAdminIfNeeded();$('#ordersBody').innerHTML=a.map(o=>`<tr><td><strong>${escapeHtml(o.order_id)}</strong><small>${escapeHtml(o.created_at)}</small></td><td>${escapeHtml(o.product)}<small>${escapeHtml(o.edition)}</small></td><td>${escapeHtml(o.customer)}<small>${escapeHtml(o.device)}</small></td><td>${escapeHtml(o.license_type)}</td><td>${rupiah(o.amount)}</td><td><span class="badge ${escapeHtml(o.payment_status)}">${escapeHtml(o.payment_status)}</span></td><td><span class="badge ${escapeHtml(o.fulfillment_status)}">${escapeHtml(o.fulfillment_status)}</span></td><td class="actions">${o.payment_mode==='manual'&&o.payment_status==='pending'?`<button data-id="${escapeHtml(o.order_id)}" data-action="mark_paid">Lunas + aktifkan</button>`:''}${o.payment_status==='paid'&&o.fulfillment_status!=='issued'?`<button data-id="${escapeHtml(o.order_id)}" data-action="fulfill">Aktifkan</button>`:''}${o.payment_status==='pending'?`<button data-id="${escapeHtml(o.order_id)}" data-action="cancel">Batalkan</button>`:''}</td></tr>`).join('');$$('.actions button').forEach(b=>b.addEventListener('click',()=>doAction(b)));}catch(e){if(e.status===401){adminLogin.classList.remove('hidden');content.classList.add('hidden')}}};
    const showAdminIfNeeded=()=>{adminLogin.classList.add('hidden');content.classList.remove('hidden')};
    const doAction=async b=>{b.disabled=true;try{await api(`/store/api/admin/order/${encodeURIComponent(b.dataset.id)}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:b.dataset.action})});await loadOrders()}catch(e){alert(e.message);b.disabled=false}};
    const loadPrices=async()=>{try{const d=await api('/store/api/admin/prices');showAdminIfNeeded();$('#priceEditor').innerHTML=Object.entries(d).map(([product,eds])=>`<article><h3>${escapeHtml(product)}</h3>${Object.entries(eds).map(([edition,p])=>`<label><span>${escapeHtml(p.label||edition)}</span><div><span>Rp</span><input type="number" min="1000" step="1000" value="${Number(p.price)}" data-product="${escapeHtml(product)}" data-edition="${escapeHtml(edition)}"><button>Simpan</button></div></label>`).join('')}</article>`).join('');$$('.price-editor button').forEach(b=>b.addEventListener('click',async()=>{const i=b.previousElementSibling;try{await api('/store/api/admin/price',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({product:i.dataset.product,edition:i.dataset.edition,price:Number(i.value)})});b.textContent='Tersimpan';setTimeout(()=>b.textContent='Simpan',1000)}catch(e){alert(e.message)}}))}catch(e){}};
    $('#adminLoginForm').addEventListener('submit',async e=>{e.preventDefault();loginErr.textContent='';try{await api('/store/api/admin/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({secret:new FormData(e.currentTarget).get('secret')})});showAdmin()}catch(ex){loginErr.textContent=ex.message}});
    $('#reloadOrders').addEventListener('click',loadOrders);$('#adminLogout').addEventListener('click',async()=>{try{await api('/store/api/admin/logout',{method:'POST'})}finally{location.reload()}});$$('.admin-tabs button').forEach(b=>b.addEventListener('click',()=>{$$('.admin-tabs button').forEach(x=>x.classList.toggle('active',x===b));$$('.tab-pane').forEach(x=>x.classList.add('hidden'));$(`#tab-${b.dataset.tab}`).classList.remove('hidden')}));
    loadOrders();
  }
})();
