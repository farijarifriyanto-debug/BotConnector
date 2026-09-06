/**
 * BotConnector AI Support V3 — Interactive Floating Chat Widget
 * Lightweight, zero-dependency client with ecosystem auto-detection, Clarity masking,
 * markdown formatting, action link navigation buttons, quick suggestion pills, and ticket escalation.
 */

(function () {
  'use strict';

  // Prevent multiple initializations
  if (window.__BC_AI_WIDGET_INITIALIZED__) return;
  window.__BC_AI_WIDGET_INITIALIZED__ = true;

  // Session handling
  var SESSION_KEY = 'bc_ai_session_id';
  var sessionId = sessionStorage.getItem(SESSION_KEY);
  if (!sessionId) {
    sessionId = 'sess_' + Math.random().toString(36).substring(2, 15) + Math.random().toString(36).substring(2, 15);
    sessionStorage.setItem(SESSION_KEY, sessionId);
  }

  // Detect ecosystem and module from URL and hash
  function getContext() {
    var path = window.location.pathname.toLowerCase();
    var hash = window.location.hash.toLowerCase();

    if (path.indexOf('/bisnis') !== -1 || hash.indexOf('/pos') !== -1 || hash.indexOf('/restaurant') !== -1 || hash.indexOf('/inventory') !== -1 || hash.indexOf('/reports') !== -1 || hash.indexOf('/products') !== -1) {
      var mod = 'General';
      if (hash.indexOf('/pos') !== -1) mod = 'Kasir POS';
      else if (hash.indexOf('/restaurant') !== -1) mod = 'Resto & KDS';
      else if (hash.indexOf('/inventory') !== -1) mod = 'Inventori';
      else if (hash.indexOf('/reports') !== -1) mod = 'Laporan Laba Rugi';
      else if (hash.indexOf('/products') !== -1) mod = 'Katalog Produk';
      else if (hash.indexOf('/transfers') !== -1) mod = 'Transfer Cabang';
      else if (hash.indexOf('/integrasi') !== -1) mod = 'Integrasi Telegram';
      return { ecosystem: 'BUSINESS_SUITE', module: mod };
    }
    if (path.indexOf('/parking') !== -1) {
      var pmod = 'Dashboard';
      var activeTab = window.ACTIVE_TAB || '';
      var prof = (window.APP_STATE && window.APP_STATE.deployment_profile) || 'FULL_STACK';
      if (activeTab === 'simulator' || hash.indexOf('/simulator') !== -1) pmod = 'Simulator';
      else if (activeTab === 'devices' || hash.indexOf('/devices') !== -1) pmod = 'Hardware & Devices';
      else if (activeTab === 'anpr' || hash.indexOf('/anpr') !== -1) pmod = 'ANPR Review';
      else if (activeTab === 'reports' || hash.indexOf('/reports') !== -1) pmod = 'Laporan';
      else if (activeTab === 'gates' || hash.indexOf('/gates') !== -1) pmod = 'Gate & Lane';
      else if (activeTab === 'live' || hash.indexOf('/live') !== -1) pmod = 'Live Parking';
      else if (activeTab === 'qris' || hash.indexOf('/qris') !== -1) pmod = 'QRIS & Gateway';
      else if (activeTab === 'api_docs' || hash.indexOf('/api') !== -1) pmod = 'Integrasi API';
      else if (activeTab === 'settings' || hash.indexOf('/settings') !== -1) pmod = 'Pengaturan';
      return { ecosystem: 'PARKING', module: pmod, profile: prof };
    }
    if (path.indexOf('/drive') !== -1) {
      return { ecosystem: 'MY_DRIVE', module: 'Cloud Storage' };
    }
    if (path.indexOf('/docs') !== -1) {
      return { ecosystem: 'PLATFORM', module: 'Dokumentasi' };
    }
    if (path.indexOf('/status') !== -1) {
      return { ecosystem: 'PLATFORM', module: 'Status Layanan' };
    }
    if (path.indexOf('/support') !== -1) {
      return { ecosystem: 'PLATFORM', module: 'Pusat Bantuan' };
    }
    return { ecosystem: 'PLATFORM', module: 'General' };
  }

  var context = getContext();

  // Create UI Root
  var widgetContainer = document.createElement('div');
  widgetContainer.id = 'bc-ai-widget-root';

  var launcher = document.createElement('button');
  launcher.className = 'bc-ai-launcher';
  launcher.setAttribute('aria-label', 'Buka Bantuan BotConnector AI');
  launcher.innerHTML = '<span class="sparkle">✦</span><span>Bantuan AI</span>';

  var windowPanel = document.createElement('div');
  windowPanel.className = 'bc-ai-window';
  windowPanel.setAttribute('data-clarity-mask', 'true');

  windowPanel.innerHTML =
    '<div class="bc-ai-header">' +
      '<div class="bc-ai-header-left">' +
        '<div class="bc-ai-header-icon">✦</div>' +
        '<div>' +
          '<h3 class="bc-ai-header-title">BotConnector AI <span class="bc-ai-status-dot"></span></h3>' +
        '</div>' +
      '</div>' +
      '<button class="bc-ai-close-btn" aria-label="Tutup">&times;</button>' +
    '</div>' +
    '<div class="bc-ai-messages" id="bc-ai-msg-list" data-clarity-mask="true"></div>' +
    '<div class="bc-ai-input-wrap">' +
      '<input type="text" class="bc-ai-input" id="bc-ai-input-field" placeholder="Tanyakan seputar fitur, panduan, atau kendala..." data-clarity-mask="true" autocomplete="off" />' +
      '<button class="bc-ai-send-btn" id="bc-ai-send-btn" aria-label="Kirim Pesan">➤</button>' +
    '</div>';

  widgetContainer.appendChild(launcher);
  widgetContainer.appendChild(windowPanel);
  document.body.appendChild(widgetContainer);

  var msgList = document.getElementById('bc-ai-msg-list');
  var inputField = document.getElementById('bc-ai-input-field');
  var sendBtn = document.getElementById('bc-ai-send-btn');
  var closeBtn = windowPanel.querySelector('.bc-ai-close-btn');

  // Toggle open/close
  var isOpen = false;
  function toggleWidget() {
    isOpen = !isOpen;
    if (isOpen) {
      windowPanel.classList.add('open');
      launcher.style.display = 'none';
      if (msgList.children.length === 0) {
        renderWelcomeMessage();
      }
      setTimeout(function () {
        inputField.focus();
      }, 100);
    } else {
      windowPanel.classList.remove('open');
      launcher.style.display = 'inline-flex';
    }
  }

  launcher.addEventListener('click', toggleWidget);
  closeBtn.addEventListener('click', toggleWidget);

  // Close on Escape key
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && isOpen) {
      toggleWidget();
    }
  });

  // Render markdown-like text safely
  function formatText(text) {
    var escaped = text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');

    // Bold
    escaped = escaped.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    // Inline code
    escaped = escaped.replace(/`([^`]+)`/g, '<code style="background:#F1F3F9;padding:2px 5px;border-radius:4px;font-family:monospace;font-size:12px;">$1</code>');
    // Bullet points
    escaped = escaped.replace(/^• (.*)$/gm, '<li style="margin-left: 16px;">$1</li>');
    escaped = escaped.replace(/^- (.*)$/gm, '<li style="margin-left: 16px;">$1</li>');
    // Links [title](url)
    escaped = escaped.replace(/\[(.*?)\]\((https?:\/\/.*?)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer" style="color: #5B5FEF; font-weight: 650; text-decoration: underline;">$1</a>');
    // Newlines
    escaped = escaped.replace(/\n/g, '<br/>');
    return escaped;
  }

  // Append message bubble
  function appendMessage(sender, htmlContent, sources, actionLinks, draftData) {
    var bubble = document.createElement('div');
    bubble.className = 'bc-ai-msg ' + sender;
    bubble.setAttribute('data-clarity-mask', 'true');
    bubble.innerHTML = htmlContent;

    // Render Action Links (Navigation Buttons)
    if (actionLinks && actionLinks.length > 0) {
      var actBox = document.createElement('div');
      actBox.className = 'bc-ai-actions';
      actionLinks.forEach(function (act) {
        var actBtn = document.createElement('a');
        actBtn.className = 'bc-ai-action-btn';
        actBtn.href = act.url;
        actBtn.target = '_blank';
        actBtn.rel = 'noopener noreferrer';
        actBtn.innerHTML = act.title + ' &rarr;';
        actBox.appendChild(actBtn);
      });
      bubble.appendChild(actBox);
    }

    // Render Canonical Sources
    if (sources && sources.length > 0) {
      var srcBox = document.createElement('div');
      srcBox.className = 'bc-ai-sources';
      var srcHtml = '<strong>Sumber resmi:</strong><br/>';
      sources.forEach(function (s) {
        srcHtml += '<a class="bc-ai-source-link" href="' + s.url + '" target="_blank" rel="noopener noreferrer">↗ ' + s.title + '</a>';
      });
      srcBox.innerHTML = srcHtml;
      bubble.appendChild(srcBox);
    }

    // Render Ticket Draft Card
    if (draftData && draftData.draft_id) {
      var draftCard = document.createElement('div');
      draftCard.className = 'bc-ai-draft-card';
      draftCard.setAttribute('data-clarity-mask', 'true');
      draftCard.innerHTML =
        '<div class="bc-ai-draft-title">Draf Tiket Bantuan Resmi</div>' +
        '<div class="bc-ai-draft-subject">' + (draftData.subject || 'Kendala Operasional') + '</div>' +
        '<div style="font-size: 12.5px; color: #475467; margin-bottom: 8px;">' + (draftData.summary || '') + '</div>' +
        '<div class="bc-ai-draft-actions">' +
          '<button class="bc-ai-btn-confirm" id="btn-confirm-' + draftData.draft_id + '">Konfirmasi &amp; Kirim Tiket</button>' +
          '<button class="bc-ai-btn-cancel" id="btn-cancel-' + draftData.draft_id + '">Batal</button>' +
        '</div>';

      bubble.appendChild(draftCard);

      setTimeout(function () {
        var confirmBtn = document.getElementById('btn-confirm-' + draftData.draft_id);
        var cancelBtn = document.getElementById('btn-cancel-' + draftData.draft_id);

        if (confirmBtn) {
          confirmBtn.addEventListener('click', function () {
            confirmTicket(draftData.draft_id, draftCard);
          });
        }
        if (cancelBtn) {
          cancelBtn.addEventListener('click', function () {
            draftCard.innerHTML = '<div style="font-size: 12.5px; color: #667085; font-style: italic;">Pengiriman tiket dibatalkan.</div>';
          });
        }
      }, 50);
    }

    msgList.appendChild(bubble);
    msgList.scrollTop = msgList.scrollHeight;
  }

  // Welcome Message & Contextual Starter Pills
  function renderWelcomeMessage() {
    var cur = getContext();
    var intro = 'Halo! Saya <strong>BotConnector AI Support</strong>, asisten spesialis untuk produk, troubleshooting, dan panduan setup BotConnector.<br/>Ada yang dapat saya bantu?';
    appendMessage('bot', intro);

    var pillsWrap = document.createElement('div');
    pillsWrap.className = 'bc-ai-pills';

    var pills = [];
    if (cur.ecosystem === 'BUSINESS_SUITE') {
      pills = [
        'Cara tambah stok',
        'Cara transaksi pertama',
        'Apa itu KOT?',
        'Cara transfer stok',
        'Kenapa produk tidak muncul di POS?',
        'Laporan laba rugi'
      ];
    } else if (cur.ecosystem === 'PARKING') {
      var pProf = cur.profile || 'FULL_STACK';
      if (pProf === 'EXISTING_HARDWARE') {
        pills = [
          'Cara hubungkan kamera saya?',
          'Cara hubungkan palang yang sudah ada?',
          'Bagaimana cek hardware kompatibel?',
          'Apa arti Physical Test Pending?',
          'Apa arti Profile M Ready?'
        ];
      } else if (pProf === 'PAYMENT_ONLY') {
        pills = [
          'Cara buat Sandbox Order?',
          'Bagaimana Payment Only bekerja?',
          'Bagaimana setup webhook?',
          'Kapan QRIS produksi bisa digunakan?',
          'Dokumentasi API Payment'
        ];
      } else {
        pills = [
          'Cara mulai menggunakan Parking?',
          'Cara simulasi kendaraan masuk?',
          'Bagaimana mengatur tarif?',
          'Apa arti Profile M Ready?',
          'Kenapa device offline?'
        ];
      }
    } else if (cur.ecosystem === 'MY_DRIVE') {
      pills = [
        'Cara upload file',
        'Kenapa file tidak terlihat?',
        'Struktur folder',
        'Pusat Bantuan'
      ];
    } else {
      pills = [
        'BotConnector itu apa?',
        'Business Suite buat apa?',
        'Parking buat apa?',
        'My Drive buat apa?',
        'Status Server',
        'Pusat Bantuan'
      ];
    }

    pills.forEach(function (pillText) {
      var pillBtn = document.createElement('button');
      pillBtn.className = 'bc-ai-pill';
      pillBtn.textContent = pillText;
      pillBtn.addEventListener('click', function () {
        sendMessage(pillText);
      });
      pillsWrap.appendChild(pillBtn);
    });

    msgList.appendChild(pillsWrap);
    msgList.scrollTop = msgList.scrollHeight;
  }

  // Contextual Thinking Microcopy Helper
  function getInitialThinkingState(text) {
    var t = text.toLowerCase();
    if (/(tidak|nggak|gagal|kenapa|rusak|pending|salah|hilang|kecewa|lambat|macet|tertagih|gangguan|error)/.test(t)) {
      return { mode: 'TROUBLESHOOTING', initialText: 'Memahami kendala Anda' };
    }
    if (/(pasang|install|setup|sambungkan|hubungkan|kamera saya|hardware sendiri|mulai dari nol|setting)/.test(t)) {
      return { mode: 'INSTALLATION', initialText: 'Memahami kebutuhan pemasangan' };
    }
    if (/(cara|bagaimana|langkah|tutorial|tambah|transfer|upload|hitung|bayar|apa itu)/.test(t)) {
      return { mode: 'HOW_TO', initialText: 'Menyiapkan panduan' };
    }
    return { mode: 'GENERAL', initialText: 'Memahami pertanyaan Anda' };
  }

  // Send message API
  function sendMessage(textOverride) {
    var text = (textOverride || inputField.value).trim();
    if (!text) return;

    inputField.value = '';
    sendBtn.disabled = true;

    appendMessage('user', formatText(text));

    // Thinking / Waiting indicator
    var thinkingState = getInitialThinkingState(text);
    var typingBubble = document.createElement('div');
    typingBubble.className = 'bc-ai-msg bot';
    typingBubble.id = 'bc-ai-typing';
    typingBubble.innerHTML =
      '<div class="bc-ai-thinking-wrap">' +
        '<span class="bc-ai-thinking-text" id="bc-ai-thinking-text">' + thinkingState.initialText + '</span>' +
        '<span class="bc-ai-dot-pulse"><span>.</span><span>.</span><span>.</span></span>' +
      '</div>';
    msgList.appendChild(typingBubble);
    msgList.scrollTop = msgList.scrollHeight;

    var startTime = Date.now();
    var thinkingTimer = setInterval(function () {
      var el = document.getElementById('bc-ai-thinking-text');
      if (!el) {
        clearInterval(thinkingTimer);
        return;
      }
      var elapsedSec = (Date.now() - startTime) / 1000;
      if (thinkingState.mode === 'TROUBLESHOOTING') {
        if (elapsedSec >= 5) {
          el.textContent = 'Menyiapkan langkah pengecekan';
        } else if (elapsedSec >= 2) {
          el.textContent = 'Mencari solusi yang sesuai';
        }
      } else if (thinkingState.mode === 'INSTALLATION') {
        if (elapsedSec >= 2) {
          el.textContent = 'Menyiapkan langkah pemasangan';
        }
      } else if (thinkingState.mode === 'HOW_TO') {
        if (elapsedSec >= 2) {
          el.textContent = 'Menyiapkan panduan';
        }
      } else {
        if (elapsedSec >= 2) {
          el.textContent = 'Menyiapkan jawaban';
        }
      }
    }, 1000);

    var curCtx = getContext();

    fetch('/v1/support-ai/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: text,
        session_id: sessionId,
        ecosystem: curCtx.ecosystem,
        module: curCtx.module
      })
    })
      .then(function (res) {
        return res.json();
      })
      .then(function (data) {
        clearInterval(thinkingTimer);
        var typing = document.getElementById('bc-ai-typing');
        if (typing) typing.remove();
        sendBtn.disabled = false;

        if (data.ok) {
          appendMessage('bot', formatText(data.response), data.sources, data.action_links, data.ticket_draft);
        } else {
          appendMessage('bot', '<em>' + (data.error || 'Terjadi kendala saat memproses permintaan.') + '</em>');
        }
      })
      .catch(function () {
        clearInterval(thinkingTimer);
        var typing = document.getElementById('bc-ai-typing');
        if (typing) typing.remove();
        sendBtn.disabled = false;
        appendMessage('bot', '<em>Gagal terhubung ke layanan AI. Anda dapat membuka panduan di <a href="/docs/" target="_blank" style="color: #5B5FEF;">Dokumentasi Master</a> atau membuat tiket di <a href="/support" target="_blank" style="color: #5B5FEF;">Pusat Bantuan</a>.</em>');
      });
  }

  // Submit confirmed ticket
  function confirmTicket(draftId, cardElement) {
    cardElement.innerHTML = '<div style="font-size: 12.5px; color: #5B5FEF; font-weight: 650;">Mengirim tiket ke tim BotConnector...</div>';

    fetch('/v1/support-ai/ticket/confirm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ draft_id: draftId })
    })
      .then(function (res) {
        return res.json();
      })
      .then(function (data) {
        if (data.ok) {
          cardElement.innerHTML =
            '<div style="background: #F0FDF4; border: 1px solid #BBF7D0; border-radius: 8px; padding: 10px; color: #166534; font-size: 12.5px;">' +
              '<strong>✓ Tiket Berhasil Terkirim</strong><br/>' +
              'Nomor Referensi: <strong>' + data.public_reference + '</strong><br/>' +
              'Tim dukungan BotConnector telah menerima pemberitahuan dan akan segera menindaklanjuti tiket ini.' +
            '</div>';
        } else {
          cardElement.innerHTML =
            '<div style="color: #DC2626; font-size: 12px;">' +
              'Gagal mengirim tiket: ' + (data.error || 'Kendala server') +
              '<br/><a href="/support" target="_blank" style="color: #5B5FEF; font-weight: 700; text-decoration: underline;">Buka formulir tiket langsung di /support</a>' +
            '</div>';
        }
      })
      .catch(function () {
        cardElement.innerHTML =
          '<div style="color: #DC2626; font-size: 12px;">' +
            'Gagal mengirim tiket. Silakan gunakan formulir tiket di <a href="/support" target="_blank" style="color: #5B5FEF; font-weight: 700;">/support</a>.' +
          '</div>';
      });
  }

  // Send on Enter
  inputField.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') {
      e.preventDefault();
      sendMessage();
    }
  });

  sendBtn.addEventListener('click', function () {
    sendMessage();
  });

})();
