/** All model and event strings use text nodes, never HTML. */
export class ChatView {
  constructor(root = document) { this.root = root; }
  node(tag, text, className = '') {
    const el = this.root.createElement(tag);
    el.textContent = text;
    el.className = className;
    return el;
  }
  profiles(rows, selected) {
    const select = this.root.getElementById('chat-profile');
    select.replaceChildren(...rows.map(row => {
      const option = this.node('option', row.display_name);
      option.value = row.id;
      return option;
    }));
    if (selected && rows.some(row => row.id === selected)) select.value = selected;
  }
  status(message, busy = false) {
    this.root.getElementById('chat-status').textContent = message;
    this.root.getElementById('chat-send').disabled = busy;
  }
  render(session, onTrack) {
    const list = this.root.getElementById('chat-messages');
    list.replaceChildren();
    const offers = new Map((session.offers || []).map(o => [o.id, o]));
    if (!session.turns.length) list.append(this.node('p', 'Ask about this match, a statistic, or a football rule.', 'muted'));
    for (const turn of session.turns) {
      list.append(this.node('p', turn.prompt, 'chat-user'));
      const reply = turn.reply;
      if (!reply) { list.append(this.node('p', 'Checking the match…', 'chat-answer muted')); continue; }
      const answer = this.node('div', '', 'chat-answer');
      answer.append(this.node('p', reply.text));
      const seconds = reply.snapshot?.clock_seconds;
      if (seconds !== undefined) answer.append(this.node('small', seconds === null ? 'Before kickoff' : `As of ${Math.floor(seconds / 60)}′ · ${reply.snapshot.period === 2 ? 'Second' : 'First'} half`));
      if (reply.evidence?.length) answer.append(this.node('div', reply.evidence.map(e => e.label).join(' · '), 'chat-evidence'));
      for (const original of reply.offers || []) {
        const offer = offers.get(original.id) || original;
        const card = this.node('div', '', 'chat-offer');
        card.append(this.node('span', offer.label), this.node('strong', String(offer.value)));
        const button = this.node('button', offer.calculation_id ? 'Tracking ✓' : 'Track this stat', 'button secondary');
        button.disabled = Boolean(offer.calculation_id);
        button.addEventListener('click', async () => {
          button.disabled = true;
          try { await onTrack(offer.id); } finally { if (button.isConnected && !offer.calculation_id) button.disabled = false; }
        });
        card.append(button); answer.append(card);
      }
      list.append(answer);
    }
    list.scrollTop = list.scrollHeight;
  }
}
