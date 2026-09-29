import { mkdir, copyFile } from 'node:fs/promises';
const output = new URL('../app/static/', import.meta.url);
await mkdir(output, { recursive: true });
for (const name of ['index.html', 'styles.css', 'app.js', 'client.js']) {
  await copyFile(new URL(`src/${name}`, import.meta.url), new URL(name, output));
}
console.log('Built frontend → app/static (served by FastAPI at /)');
