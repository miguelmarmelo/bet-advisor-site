/* Bet Advisor — lógica partilhada pelas páginas do painel. Lê data/panel.json e data/tracker.json. */
'use strict';
const CATS = ['1X2', 'Golos 2,5', 'Outras linhas de golos', 'Ambas marcam', 'Dupla hipótese', 'Empate anula aposta', 'Cantos', '1.ª parte'];
const STATUS = { '1X2': 'ok', 'Golos 2,5': 'pouco' };
const tested = c => STATUS[c] === 'ok';
const statusTxt = c => STATUS[c] === 'pouco' ? 'Desaconselhado por agora: o teste com jogos passados teve poucas apostas' : 'Desaconselhado por agora: este tipo de aposta ainda não foi testado';
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
const fmt = (x, n) => x.toFixed(n === undefined ? 2 : n).replace('.', ',');
const eur = e => (e >= 0 ? '+' : '−') + fmt(Math.abs(e) * 100) + ' €';
const CHIP = { valor: ['c-valor', 'Vale a pena'], marginal: ['c-marginal', 'Por pouco'], desatualizada: ['c-desatualizada', 'Odd desatualizada'], nada: ['c-nada', 'Sem vantagem'] };
const chipFor = o => tested(o.cat) ? `<span class="chip ${CHIP[o.cls][0]}">${CHIP[o.cls][1]}</span>` : '<span class="chip c-desac">Desaconselhado</span>';

const state = { days: 1, casas: 'pt', cats: CATS.slice() };
let D = null;

function lim() { return D.dates[state.days]; }
function options() {
  const src = state.casas === 'pt' ? D.pt : D.intl;
  return src.map(r => ({ date: r[0], jogo: r[1], comp: r[2], quando: r[3], cat: r[4], aposta: r[5], fair: r[6], odd: r[7], ev: r[8], cls: r[9], casa: r[10], aviso: r[11] }))
    .filter(o => o.date <= lim() && state.cats.indexOf(o.cat) >= 0);
}

function renderFilters(el, rerender) {
  const b = (label, on, attrs) => `<button type="button" class="btn" aria-pressed="${on}" ${attrs}>${esc(label)}</button>`;
  const allOn = state.cats.length === CATS.length;
  el.innerHTML = `
    <div class="frow">
      <div class="fgroup"><span class="flabel">Jogos nos próximos</span>
        <div class="btns" role="group" aria-label="Jogos nos próximos dias">${[1, 2, 3, 4, 5, 6, 7].map(d => b(d === 1 ? '1 dia' : d + ' dias', d === state.days, `data-days="${d}"`)).join('')}</div>
        <span class="small">${esc(D.labs[String(state.days)])}</span></div>
      <div class="fgroup"><span class="flabel">Casas</span>
        <div class="btns" role="group" aria-label="Casas">${b('Só portuguesas (betano.pt)', state.casas === 'pt', 'data-casas="pt"')}${b('Todas as casas', state.casas === 'todas', 'data-casas="todas"')}</div></div>
    </div>
    <div class="fgroup"><span class="flabel">Tipos de aposta: "Todos" ou carrega nos que queres juntar (ex.: 1X2 + Golos 2,5)</span>
      <div class="btns" role="group" aria-label="Tipos de aposta">${b('Todos', allOn, 'data-all="1"')}${CATS.map(c => b(c + (tested(c) ? '' : ' *'), !allOn && state.cats.indexOf(c) >= 0, `data-cat="${esc(c)}"`)).join('')}</div>
      <span class="small">* desaconselhado por agora: tipo de aposta sem teste com jogos passados, ou com poucas apostas no teste</span></div>`;
  el.querySelectorAll('[data-days]').forEach(x => x.onclick = () => { state.days = +x.dataset.days; rerender(); });
  el.querySelectorAll('[data-casas]').forEach(x => x.onclick = () => { state.casas = x.dataset.casas; rerender(); });
  el.querySelector('[data-all]').onclick = () => { state.cats = CATS.slice(); rerender(); };
  el.querySelectorAll('[data-cat]').forEach(x => x.onclick = () => {
    const c = x.dataset.cat;
    if (state.cats.length === CATS.length) { state.cats = [c]; rerender(); return; }
    const on = state.cats.indexOf(c) >= 0;
    const nxt = on ? state.cats.filter(y => y !== c) : state.cats.concat([c]);
    state.cats = nxt.length ? nxt : [c]; rerender();
  });
  const notes = [];
  const last = D.dates[D.dates.length - 1];
  const anyDays = Object.keys(state.casas === 'pt' ? D.gamesPT : D.gamesIntl).filter(d => d > lim()).length;
  if (!D.ptFresh && state.casas === 'pt') notes.push('<p class="note warn">As odds da betano.pt não foram atualizadas nesta execução (limite mensal de pedidos); estes números são da atualização anterior.</p>');
  if (state.casas === 'todas' && state.cats.some(c => c !== '1X2')) notes.push('<p class="note warn">Com "Todas as casas" só temos odds de várias casas para o resultado final (1X2). Os outros tipos de aposta só estão disponíveis para a betano.pt.</p>');
  document.getElementById('notes').innerHTML = notes.join('');
}

function gamesCount() {
  const g = state.casas === 'pt' ? D.gamesPT : D.gamesIntl;
  return Object.keys(g).filter(d => d <= lim()).reduce((s, d) => s + g[d], 0);
}
function analysedCount() {
  return Object.keys(state.casas === 'pt' ? D.countsPT : D.countsIntl).filter(d => d <= lim()).reduce((s, d) => s +
    (state.casas === 'pt' ? state.cats.reduce((t, c) => t + ((D.countsPT[d] || {})[c] || 0), 0) : (state.cats.indexOf('1X2') >= 0 ? D.countsIntl[d] : 0)), 0);
}

/* ---------------- página: melhores oportunidades ---------------- */
function renderJornada() {
  renderFilters(document.getElementById('filters'), renderJornada);
  const all = options();
  const nvalor = all.filter(o => tested(o.cat) && o.cls === 'valor').length;
  const nmarg = all.filter(o => tested(o.cat) && o.cls === 'marginal').length;
  const ndesat = all.filter(o => tested(o.cat) && o.cls === 'desatualizada').length;
  const ndesac = all.filter(o => !tested(o.cat) && o.ev >= 0.02).length;
  document.getElementById('gen').textContent = `${gamesCount()} jogos · odds atualizadas ${D.generatedTxt}. Para cada aposta comparamos a odd da casa com a hipótese real de o resultado acontecer.`;
  document.getElementById('kpis').innerHTML = `
    <div class="card kpi"><span class="k">Apostas analisadas</span><span class="v">${analysedCount()}</span><span class="s">${gamesCount()} jogos, nos tipos de aposta escolhidos</span></div>
    <div class="card kpi"><span class="k">Valem a pena</span><span class="v" style="color:var(--good)">${nvalor}</span><span class="s">só tipos de aposta já testados</span></div>
    <div class="card kpi"><span class="k">Por pouco · Odd desatualizada</span><span class="v"><span style="color:var(--warn)">${nmarg}</span> · <span style="color:var(--brand)">${ndesat}</span></span><span class="s">registadas para ver se acertam, sem recomendação</span></div>
    <div class="card kpi"><span class="k">Desaconselhadas com ganho ≥ 2 €</span><span class="v" style="color:var(--muted)">${ndesac}</span><span class="s">tipos de aposta ainda por testar</span></div>
    <div class="card kpi"><span class="k">Conselho para este período</span><span class="v txt">${nvalor === 0 ? 'Não apostar' : nvalor === 1 ? '1 aposta vale a pena' : nvalor + ' apostas valem a pena'}</span><span class="s">${nvalor === 0 ? 'nenhuma opção testada cumpre os critérios' : 'confirma se a casa funciona em Portugal antes de apostar'}</span></div>`;
  const rows = all.slice().sort((a, b) => b.ev - a.ev).slice(0, 10);
  document.getElementById('top').innerHTML = rows.length === 0 ? '<p style="margin:0;padding:24px">Não há apostas para mostrar com estes filtros.</p>' : `
    <table style="min-width:1080px"><thead><tr><th>#</th><th>Jogo</th><th>Aposta</th><th class="r">Hipótese real</th><th class="r">Odd mínima para compensar</th><th class="r">Odd</th><th class="r">Ganho esperado por 100 €</th><th>Classificação</th></tr></thead><tbody>
    ${rows.map((o, i) => `<tr>
      <td class="mono" style="color:var(--muted)">${i + 1}</td>
      <td><strong>${esc(o.jogo)}</strong><div class="small">${esc(o.comp)} · ${esc(o.quando)}</div></td>
      <td><strong>${esc(o.aposta)}</strong><div class="small">${esc(o.cat)}</div></td>
      <td class="r mono">${Math.round(o.fair * 100)}%</td><td class="r mono">${fmt(1 / o.fair)}</td>
      <td class="r"><div class="mono"><strong>${fmt(o.odd)}</strong></div><div class="small">${esc(o.casa)}</div></td>
      <td class="r mono"><strong>${eur(o.ev)}</strong></td>
      <td>${chipFor(o)}<div class="small" style="max-width:240px;margin-top:4px">${esc(!tested(o.cat) ? statusTxt(o.cat) : (o.aviso || (o.cls === 'nada' ? 'Ganho esperado abaixo de 2 €' : '')))}</div></td></tr>`).join('')}
    </tbody></table>`;
}

/* ---------------- página: combinadas ---------------- */
function renderCombinadas() {
  renderFilters(document.getElementById('filters'), renderCombinadas);
  const pool = options().filter(o => o.odd <= 8);
  const pick = list => { const used = {}; const out = []; list.slice().sort((a, b) => b.ev - a.ev).forEach(o => { if (!used[o.jogo] && out.length < 3) { used[o.jogo] = 1; out.push(o); } }); return out; };
  const rec = pick(pool.filter(o => tested(o.cat) && o.cls === 'valor'));
  const legs = rec.length >= 2 ? rec : pick(pool);
  const recomendada = legs.length >= 2 && legs.every(o => tested(o.cat) && o.cls === 'valor');
  const box = document.getElementById('combo');
  document.getElementById('comboSub').textContent = `${D.labs[String(state.days)]} · ${state.casas === 'pt' ? 'casas portuguesas (betano.pt)' : 'todas as casas'}`;
  if (legs.length < 2) {
    box.innerHTML = '<div class="empty"><strong>Com estes filtros não há jogos suficientes para uma combinada</strong> (são precisos pelo menos 2 jogos diferentes com odds até 8).</div>';
  } else {
    const off = legs.reduce((s, o) => s * o.odd, 1), p = legs.reduce((s, o) => s * o.fair, 1), evc = p * off - 1;
    const nD = legs.filter(o => !tested(o.cat)).length, nF = legs.filter(o => tested(o.cat) && o.cls !== 'valor').length;
    const mot = []; if (nD) mot.push(nD === 1 ? '1 aposta é de um tipo ainda desaconselhado' : nD + ' apostas são de tipos ainda desaconselhados');
    if (nF) mot.push(nF === 1 ? '1 aposta não chega a "Vale a pena"' : nF + ' apostas não chegam a "Vale a pena"');
    const txt = recomendada ? `Compensa em média, mas só acerta cerca de 1 vez em cada ${Math.round(1 / p)}. Na maior parte das vezes perdes o que apostaste.`
      : `É a melhor combinação possível com estes filtros, mas não é recomendada: ${mot.join(' e ')}. Em média, por cada 100 € recebes de volta ${Math.round((evc + 1) * 100)} €.`;
    box.innerHTML = `<div class="split"><div class="grow card tablewrap"><table style="min-width:580px"><thead><tr><th>Aposta</th><th class="r">Hipótese real</th><th class="r">Odd</th><th class="r">Ganho esperado por 100 €</th></tr></thead><tbody>
      ${legs.map(o => `<tr><td><strong>${esc(o.aposta)}</strong><div class="small">${esc(o.jogo)} · ${esc(o.comp)} · ${esc(o.quando)} · ${esc(o.cat)} · ${esc(o.casa)}</div>
        <div style="margin-top:6px">${chipFor(o)}</div>${o.date > D.dates[2] ? '<div class="small" style="color:var(--warn)">Jogo daqui a mais de 2 dias: ainda não se sabem lesões nem onzes</div>' : ''}</td>
        <td class="r mono">${Math.round(o.fair * 100)}%</td><td class="r mono"><strong>${fmt(o.odd)}</strong></td><td class="r mono"><strong>${eur(o.ev)}</strong></td></tr>`).join('')}
      </tbody></table></div>
      <div class="dark"><span class="${recomendada ? 'badge-ok' : 'badge-no'}">${recomendada ? 'Recomendada' : 'Não recomendada'}</span>
        <div class="g"><div><div class="k">Odd da combinada</div><div class="v">${fmt(off)}</div></div><div><div class="k">Odd que seria justa</div><div class="v">${fmt(1 / p)}</div></div>
        <div><div class="k">Hipótese de acertar todas</div><div class="v">${fmt(p * 100, 1)}%</div></div><div><div class="k">Ganho esperado por 100 €</div><div class="v">${eur(evc)}</div></div></div>
        <p>${esc(txt)}</p></div></div>
      <p class="foot" style="font-size:14px">Antes de apostar, confirma se as casas funcionam em Portugal e se as odds ainda estão disponíveis.</p>`;
  }
  const ex = state.casas === 'pt' ? D.exPT[String(state.days)] : D.exIntl[String(state.days)];
  document.getElementById('exTxt').textContent = state.casas === 'pt' ? 'Exemplo com os três maiores favoritos deste período, às odds da betano.pt.' : 'Exemplo com os três maiores favoritos deste período, à melhor odd internacional.';
  document.getElementById('ex').innerHTML = !ex ? '<div class="empty">Ainda não há jogos suficientes neste período.</div>' : `<div class="split">
    <div class="grow card tablewrap"><table style="min-width:620px"><thead><tr><th>Aposta</th><th class="r">Hipótese real</th><th class="r">Odd mínima para compensar</th><th class="r">Odd oferecida</th><th class="r">Ganho esperado por 100 €</th></tr></thead><tbody>
    ${ex.legs.map(l => `<tr><td><strong>${esc(l.sel)}</strong><div class="small">${esc(l.jogo)}</div></td><td class="r mono">${esc(l.justa)}</td><td class="r mono">${esc(l.min)}</td><td class="r mono"><strong>${esc(l.odd)}</strong></td><td class="r mono" style="color:${l.vant.charAt(0) === '+' ? 'var(--good)' : '#A3361F'}"><strong>${esc(l.vant)}</strong></td></tr>`).join('')}
    </tbody></table></div>
    <div class="dark"><h3 style="margin:0;font-size:18px">Em média, por cada 100 € nesta combinada recebes de volta ${ex.volta} €</h3>
      <div class="g"><div><div class="k">Odd da combinada</div><div class="v">${esc(ex.odd)}</div></div><div><div class="k">Odd que seria justa</div><div class="v">${esc(ex.justa)}</div></div>
      <div><div class="k">Hipótese de acertar as três</div><div class="v">${esc(ex.prob)}</div></div><div><div class="k">Ganho esperado por 100 €</div><div class="v" style="color:${ex.volta < 100 ? '#FF9B85' : '#7FE0BF'}">${esc(ex.ev)}</div></div></div>
      <p>${ex.volta < 100 ? 'Cada favorito sozinho já perde um pouco, porque a casa paga menos do que devia. Ao juntá-los, as perdas acumulam-se.' : 'Aqui a melhor odd de cada favorito está ligeiramente acima da justa, mas a diferença é tão pequena que pode desaparecer até ao jogo. Não é um conselho para apostar.'}</p></div></div>`;
}

/* ---------------- página: resultados (registo ao vivo) ---------------- */
function renderResultados(T) {
  const g = T.grupos;
  const card = (k) => { const x = g[k];
    return `<div class="card pad" style="display:flex;flex-direction:column;gap:10px"><strong style="font-size:17px">${esc(x.nome)}</strong>
      <div><div class="k" style="font-size:13px;color:var(--muted);font-weight:600">Acertadas</div>
      <div class="mono" style="font-size:30px;font-weight:600">${x.acertos}<span style="color:var(--muted);font-weight:400"> de ${x.resolvidas}</span></div>
      <div class="small">${x.resolvidas ? 'Seria normal acertar ' + fmt(x.esperado, 1) : 'Ainda nenhum jogo terminado'} · ${x.pendentes} à espera do jogo</div></div>
      <div class="small" style="font-size:13px">Lucro por cada 100 € apostados: <strong class="mono">${x.lucro100 == null ? '—' : (x.lucro100 >= 0 ? '+' : '−') + fmt(Math.abs(x.lucro100)) + ' €'}</strong><br>
      Apanhou odd melhor do que a última vista antes do jogo: <strong>${x.melhor == null ? '—' : x.melhor + '%'}</strong></div></div>`; };
  document.getElementById('liveDesde').textContent = T.desde ? 'Desde ' + T.desde.slice(0, 10).split('-').reverse().join('/') + '.' : '';
  document.getElementById('liveKpis').innerHTML = ['valor', 'marginal', 'desatualizada', 'desaconselhado'].map(card).join('');
  const u = T.ultimas;
  document.getElementById('liveUlt').innerHTML = u.length === 0 ? '<p style="margin:0;padding:20px">Ainda nenhum jogo assinalado terminou. Os primeiros resultados aparecem depois da próxima atualização.</p>' :
    `<table style="min-width:900px"><thead><tr><th>Jogo</th><th>Aposta</th><th class="r">Odd</th><th>Resultado</th><th>Acertou?</th><th class="r">Lucro com 1 €</th><th>Odd melhor do que a última vista?</th></tr></thead><tbody>
    ${u.map(e => `<tr><td><strong>${esc(e.jogo)}</strong><div class="small">${esc(e.comp)} · ${esc(e.quando)} · ${esc(e.grupo)}</div></td><td>${esc(e.aposta)}<div class="small">${esc(e.cat)} · ${esc(e.casa)}</div></td>
      <td class="r mono">${esc(e.odd)}</td><td class="mono">${esc(e.res || '—')}</td><td>${esc(e.acertou)}</td><td class="r mono"><strong>${esc(e.lucro)}</strong></td><td>${esc(e.melhor)}</td></tr>`).join('')}</tbody></table>`;
}

async function boot() {
  const page = document.body.dataset.page;
  try {
    if (page === 'resultados') {
      const T = await (await fetch('data/tracker.json', { cache: 'no-store' })).json();
      renderResultados(T);
      return;
    }
    D = await (await fetch('data/panel.json', { cache: 'no-store' })).json();
    if (page === 'jornada') renderJornada();
    if (page === 'combinadas') renderCombinadas();
  } catch (err) {
    document.querySelector('main').insertAdjacentHTML('afterbegin', '<p class="note warn">Não foi possível carregar os dados. Tenta recarregar a página.</p>');
  }
}
document.addEventListener('DOMContentLoaded', boot);
