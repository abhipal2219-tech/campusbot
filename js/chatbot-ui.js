const UI = {
    msgEl: document.getElementById('chatMessages'),
    inputEl: document.getElementById('userInput'),
    sendBtn: document.getElementById('sendBtn'),
    isBusy: false,

    init() {
        this.sendBtn.addEventListener('click', () => this.handleSend());
        this.inputEl.addEventListener('keydown', (e) => e.key === 'Enter' && this.handleSend());
        this.welcome();
    },

    welcome() {
        this.addMessage('bot', `👋 Hello! I'm <strong>Campus Connect</strong>.<br><br>I can help you find classrooms, faculty cabins, and section details for UEM Kolkata.`);
        this.addChips(['Where is Section G?', 'Where is the library?', 'Show all Physics teachers']);
    },

    async handleSend() {
        const text = this.inputEl.value.trim();
        if (!text || this.isBusy) return;

        this.addMessage('user', text);
        this.inputEl.value = '';
        this.showTyping();

        try {
            const reply = await window.SearchEngine.findResponse(text);
            this.hideTyping();
            if (reply) {
                this.addMessage('bot', reply.replace(/\n/g, '<br>'));
            } else {
                this.addMessage('bot', "🤔 I couldn't find a direct match. Try asking about a specific section, room number, or faculty name.");
            }
        } catch (e) {
            this.hideTyping();
            this.addMessage('bot', "❌ Sorry, I encountered an error. Please try again.");
        }
    },

    addMessage(role, html) {
        const wrap = document.createElement('div');
        wrap.className = `msg ${role}`;
        if (role === 'bot') wrap.innerHTML = `<div class="msg-avatar">🎓</div>`;
        const bub = document.createElement('div');
        bub.className = 'bubble';
        bub.innerHTML = html;
        wrap.appendChild(bub);
        if (role === 'user') wrap.innerHTML = `<div class="msg-avatar" style="background:linear-gradient(135deg,#9333ea,#ec4899)">👤</div>` + wrap.innerHTML;
        this.msgEl.appendChild(wrap);
        this.msgEl.scrollTop = this.msgEl.scrollHeight;
    },

    addChips(chips) {
        const div = document.createElement('div');
        div.className = 'quick-replies';
        chips.forEach(c => {
            const btn = document.createElement('button');
            btn.className = 'quick-btn';
            btn.textContent = c;
            btn.onclick = () => { div.remove(); this.inputEl.value = c; this.handleSend(); };
            div.appendChild(btn);
        });
        this.msgEl.appendChild(div);
        this.msgEl.scrollTop = this.msgEl.scrollHeight;
    },

    showTyping() {
        this.isBusy = true;
        const w = document.createElement('div');
        w.className = 'msg bot';
        w.id = 'typing';
        w.innerHTML = `<div class="msg-avatar">🎓</div><div class="bubble typing-dots"><span></span><span></span><span></span></div>`;
        this.msgEl.appendChild(w);
        this.msgEl.scrollTop = this.msgEl.scrollHeight;
    },

    hideTyping() {
        const t = document.getElementById('typing');
        if (t) t.remove();
        this.isBusy = false;
    }
};

window.UI = UI;
