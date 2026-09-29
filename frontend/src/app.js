import { requestTriage, safeIssueUrl } from './client.js';
const $ = id => document.getElementById(id);
const form = $('triage-form');
const count = () => { $('count').textContent = `${$('body').value.length.toLocaleString()} / 8,000`; };
$('body').addEventListener('input', count);
$('example').addEventListener('click', () => {
  $('repository').value = 'pallets/flask';
  $('title').value = 'Blueprint renders a template from the wrong folder';
  $('body').value = 'I have two Flask blueprints, each with its own templates folder and an index.html file. Calling render_template("index.html") from the second blueprint renders the first blueprint’s template. I expected it to use the template in the second blueprint’s folder.';
  count(); $('title').focus();
});
function element(tag, text, className) {
  const node = document.createElement(tag); node.textContent = text;
  if (className) node.className = className;
  return node;
}
form.addEventListener('submit', async event => {
  event.preventDefault();
  if (!$('title').value.trim()) { $('title').focus(); return; }
  $('submit').disabled = true; $('example').disabled = true;
  $('submit').textContent = 'Reviewing report…';
  $('output').setAttribute('aria-busy', 'true');
  $('results').hidden = true; $('error').hidden = true; $('status').hidden = false;
  $('status').replaceChildren(element('div', '◎', 'lens'), element('h2', 'Finding context…'), element('p', 'Searching imported issues and reviewing your report locally. The first request can take a little longer.'));
  try {
    const data = await requestTriage({ repository: $('repository').value.trim(), title: $('title').value.trim(), body: $('body').value });
    $('missing').replaceChildren(...(data.missing_information.length ? data.missing_information : ['No additional details requested.']).map(text => element('li', text)));
    $('candidates').replaceChildren();
    for (const candidate of data.candidates) {
      const card = element('article', '', 'panel candidate');
      const top = element('div', '', 'candidate-top');
      top.append(element('span', `ISSUE #${candidate.number}`), element('span', `Similarity ${candidate.similarity_score.toFixed(3)}`, 'similarity'));
      const heading = element('h3', '');
      const url = safeIssueUrl(candidate.html_url);
      const link = element(url ? 'a' : 'span', candidate.title);
      if (url) { link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer'; }
      heading.append(link); card.append(top, heading, element('p', candidate.overlap_explanation));
      $('candidates').append(card);
    }
    if (!data.candidates.length) $('candidates').append(element('p', 'No embedded candidates found. Import and embed issues for this repository.'));
    $('results').hidden = false;
  } catch (error) {
    $('error').textContent = error.message; $('error').hidden = false;
  } finally {
    $('status').hidden = true; $('submit').disabled = false; $('example').disabled = false;
    $('submit').textContent = 'Review report →'; $('output').setAttribute('aria-busy', 'false');
  }
});
