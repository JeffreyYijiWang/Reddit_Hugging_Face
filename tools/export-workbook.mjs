import fs from 'node:fs/promises';
import path from 'node:path';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

const [inputPath, outputPath] = process.argv.slice(2);
if (!inputPath || !outputPath) throw new Error('Usage: export-workbook.mjs input.json output.xlsx');
const data = JSON.parse(await fs.readFile(inputPath, 'utf8'));
const workbook = Workbook.create();
function letter(n) { let s = ''; while (n > 0) { n--; s = String.fromCharCode(65 + n % 26) + s; n = Math.floor(n / 26); } return s; }
function safe(value) {
  if (value === null || value === undefined) return null;
  if (typeof value === 'object') value = JSON.stringify(value);
  if (typeof value === 'string' && (/^\d+(\.\d+)?$/.test(value) || /^\d{4}-\d\d-\d\dT/.test(value))) return "'" + value;
  return typeof value === 'string' && /^[\s]*[=+@-]/.test(value) ? "'" + value : value;
}
const summaries = [];
for (const [name, table] of Object.entries(data)) {
  const sheet = workbook.worksheets.add(name);
  sheet.showGridLines = false;
  const headers = table.headers, rows = table.rows;
  const end = letter(headers.length), last = Math.max(1, rows.length + 1);
  sheet.getRange(`A1:${end}1`).values = [headers];
  for (let start = 0; start < rows.length; start += 1000) {
    const chunk = rows.slice(start, start+1000).map(row => row.map((value,col) => name === 'Summary' && row[0] === 'Exported at UTC' && col === 1 ? new Date(value) : safe(value)));
    sheet.getRange(`A${start+2}:${end}${start+chunk.length+1}`).values = chunk;
  }
  const used = sheet.getRange(`A1:${end}${last}`);
  used.format.font = {name: 'Arial', size: 10, color: '#243246'};
  used.format.rowHeight = 28;
  used.format.columnWidth = 24;
  used.format.verticalAlignment = 'top';
  const header = sheet.getRange(`A1:${end}1`);
  header.format.fill = '#243B53';
  header.format.font = {name: 'Arial', size: 10, color: '#FFFFFF', bold: true};
  header.format.wrapText = true;
  header.format.rowHeight = name === 'Review' ? 108 : 48;
  sheet.freezePanes.freezeRows(1);
  if (headers.length > 5) sheet.freezePanes.freezeColumns(1);
  if (name === 'Summary') {
    sheet.getRange(`A1:A${last}`).format.columnWidth = 55;
    sheet.getRange(`B1:B${last}`).format.columnWidth = 100;
    sheet.getRange(`A2:B${last}`).format.wrapText = true;
    sheet.getRange(`A2:B${last}`).format.rowHeight = 42;
    sheet.getRange('B2').setNumberFormat('yyyy-mm-dd hh:mm:ss');
  }
  if (name === 'Codebook') {
    sheet.getRange(`A1:A${last}`).format.columnWidth = 25;
    sheet.getRange(`B1:B${last}`).format.columnWidth = 65;
    sheet.getRange(`C1:C${last}`).format.columnWidth = 75;
  }
  if (name === 'Field availability') {
    sheet.getRange(`A1:A${last}`).format.columnWidth = 75;
    sheet.getRange(`B1:B${last}`).format.columnWidth = 65;
    sheet.getRange(`C1:C${last}`).format.columnWidth = 50;
    sheet.getRange(`D1:D${last}`).format.columnWidth = 90;
  }
  if (name === 'Run coverage') sheet.getRange(`B1:B${last}`).format.columnWidth = 65;
  if (name === 'Keyword hits') sheet.getRange(`A1:A${last}`).format.columnWidth = 75;
  if (name === 'Series links') sheet.getRange(`D1:D${last}`).format.columnWidth = 45;
  if (name === 'Incidents') {
    sheet.getRange(`A1:A${last}`).format.columnWidth = 30;
    sheet.getRange(`B1:C${last}`).format.columnWidth = 42;
  }
  for (let col = 0; col < headers.length; col++) {
    const h = headers[col], range = sheet.getRange(`${letter(col+1)}2:${letter(col+1)}${Math.max(2,last)}`);
    if (/(?:text|title|body|quote|rationale|notes|context)/i.test(h)) {
      range.format.columnWidth = 54;
      // Full text is retained. Compact row heights allow filtering; readers expand rows as needed.
      range.format.wrapText = false;
    }
    if (h === 'Reviewer label') range.dataValidation = {rule: {type:'list',values:['Yes','No','Unsure']}};
    if (/^Reviewer/.test(h)) range.format.fill = '#FFF4CE';
  }
  if (name === 'Review' || name === 'Incidents') sheet.tabColor = '#243B53';
  if (rows.length) {
    const t = sheet.tables.add(`A1:${end}${last}`, true, name.replace(/[^A-Za-z]/g,'') + 'Table');
    t.showFilterButton = true;
  }
  summaries.push({name, rows: rows.length, columns: headers.length});
}
workbook.recalculate();
await fs.mkdir(path.dirname(outputPath), {recursive:true});
const inspection = await workbook.inspect({kind:'table', range:'Summary!A1:B15', include:'values,formulas', tableMaxRows:15, tableMaxCols:2, maxChars:3000});
await fs.writeFile(path.join(path.dirname(outputPath),'workbook_inspection.ndjson'), inspection.ndjson);
const errors = await workbook.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#SPILL!|#CALC!', options:{useRegex:true,maxResults:100}, maxChars:3000});
await fs.writeFile(path.join(path.dirname(outputPath),'workbook_errors.ndjson'), errors.ndjson);
const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(outputPath + '.tmp.xlsx');
await fs.rename(outputPath + '.tmp.xlsx', outputPath);
// Initial and final snapshots render every sheet's populated header/sample range.
if (process.env.REID_RENDER !== '0') {
  for (const {name, rows, columns} of summaries) {
    const blob = await workbook.render({sheetName:name,range:`A1:${letter(Math.min(columns,5))}${Math.min(rows+1,6)}`,scale:1,format:'png'});
    await fs.writeFile(path.join(path.dirname(outputPath),`preview-${name.replaceAll(' ','-')}.png`),new Uint8Array(await blob.arrayBuffer()));
  }
}
await fs.writeFile(outputPath + '.verification.json',JSON.stringify({saved:outputPath,sheets:summaries,formula_policy:'All source content is literal; formula prefixes escaped',exportedAt:new Date().toISOString()},null,2));
console.log(JSON.stringify({saved:outputPath,sheets:summaries}));
