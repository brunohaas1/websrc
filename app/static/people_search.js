// people_search.js

document.addEventListener('DOMContentLoaded', function() {
  const btnTab = document.getElementById('btnPeopleSearchTab');
  const peopleTab = document.getElementById('people-search-tab');
  const financeMain = document.querySelector('main.fin-grid');
  const form = document.getElementById('people-search-form');
  const loading = document.getElementById('people-search-loading');
  const exportBtn = document.getElementById('people-export-json');

  let lastResults = null;

  btnTab.addEventListener('click', () => {
    peopleTab.style.display = 'block';
    financeMain.style.display = 'none';
  });

  form.addEventListener('submit', async function(e) {
    e.preventDefault();
    const name = document.getElementById('person-name').value;
    loading.style.display = 'inline';
    exportBtn.style.display = 'none';
    clearResults();
    try {
      const resp = await fetch('/api/people_search', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name})
      });
      const data = await resp.json();
      lastResults = data;
      renderResults(data);
      exportBtn.style.display = 'inline';
    } catch {
      renderError('Erro ao buscar informações.');
    } finally {
      loading.style.display = 'none';
    }
  });

  exportBtn.addEventListener('click', function() {
    if (!lastResults) return;
    const blob = new Blob([JSON.stringify(lastResults, null, 2)], {type: 'application/json'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'busca_pessoas.json';
    a.click();
    URL.revokeObjectURL(url);
  });

  function clearResults() {
    ['people-general','people-professional','people-social','people-news','people-links'].forEach(id => {
      document.getElementById(id).innerHTML = '';
    });
  }

  function renderResults(data) {
    for (const cat in data) {
      let el;
      switch(cat) {
        case 'Informações Gerais': el = document.getElementById('people-general'); break;
        case 'Profissional': el = document.getElementById('people-professional'); break;
        case 'Redes Sociais': el = document.getElementById('people-social'); break;
        case 'Notícias': el = document.getElementById('people-news'); break;
        case 'Links Relevantes': el = document.getElementById('people-links'); break;
        default: continue;
      }
      el.innerHTML = data[cat].map((item, idx) =>
        `<div class="people-result-item">
          <a href="${item.link}" target="_blank"><strong>${item.titulo}</strong></a>
          <span class="people-score">Relevância: ${item.score !== undefined ? item.score : '-'}</span>
          <button class="people-expand-btn" data-cat="${cat}" data-idx="${idx}">Expandir</button>
          <div class="people-detail" style="display:none">${item.descricao}</div>
        </div>`
      ).join('');
    }
    // Adiciona evento para expandir detalhes
    document.querySelectorAll('.people-expand-btn').forEach(btn => {
      btn.addEventListener('click', function() {
        const parent = btn.parentElement;
        const detail = parent.querySelector('.people-detail');
        detail.style.display = detail.style.display === 'none' ? 'block' : 'none';
      });
    });
  }

  function renderError(msg) {
    document.getElementById('people-general').innerHTML = `<span style="color:red">${msg}</span>`;
  }
});
