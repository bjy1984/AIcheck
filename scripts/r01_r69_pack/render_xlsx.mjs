import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const TEST_WARNING = "测试专用／合成资料／不得用于真实工程";
const TEST_WARNING_ASCII = "TEST-ONLY / SYNTHETIC / NOT FOR REAL ENGINEERING USE";

function columnLetter(index) {
  let result = "";
  let n = index + 1;
  while (n > 0) {
    const rem = (n - 1) % 26;
    result = String.fromCharCode(65 + rem) + result;
    n = Math.floor((n - 1) / 26);
  }
  return result;
}

function normalizeRows(sheet) {
  if (sheet.tables?.length) {
    const tables = [];
    for (const table of sheet.tables) {
      if (table.title) {
        tables.push({
          name: table.title.slice(0, 31),
          headers: table.headers ?? [],
          rows: table.rows ?? [],
        });
      } else {
        tables.push(table);
      }
    }
    return tables;
  }
  return [{ headers: sheet.headers ?? [], rows: sheet.rows ?? [] }];
}

async function buildWorkbook(payload, outputPath, previewDir) {
  const workbook = Workbook.create();
  const sheets = payload.workbook?.sheets?.length
    ? payload.workbook.sheets
    : [{ name: "记录", headers: ["项目", "内容"], rows: [["状态", "合格"]] }];

  for (const sheetData of sheets) {
    const sheetName = String(sheetData.name ?? "记录").slice(0, 31);
    const sheet = workbook.worksheets.add(sheetName);
    const tables = normalizeRows(sheetData);
    const maxColumns = Math.max(
      5,
      ...tables.map((table) => table.headers.length),
      ...tables.flatMap((table) => table.rows.map((row) => row.length)),
    );
    const lastColumn = columnLetter(maxColumns - 1);
    sheet.mergeCells(`A1:${lastColumn}1`);
    sheet.getRange("A1").values = [[payload.title ?? "工程记录"]];
    sheet.mergeCells(`A2:${lastColumn}2`);
    sheet.getRange("A2").values = [[
      `${TEST_WARNING}｜${TEST_WARNING_ASCII}｜文件编号：${payload.document_number ?? payload.logical_id ?? ""}｜版本：${payload.revision ?? "A"}｜日期：${payload.date ?? ""}`,
    ]];
    sheet.getRange(`A1:${lastColumn}1`).format = {
      fill: "#264A73",
      font: { bold: true, color: "#FFFFFF", size: 15, name: "Arial Unicode MS" },
      horizontalAlignment: "center",
      verticalAlignment: "center",
      rowHeight: 30,
    };
    sheet.getRange(`A2:${lastColumn}2`).format = {
      fill: "#FCE8E6",
      font: { bold: true, color: "#B3261E", size: 9, name: "Arial Unicode MS" },
      horizontalAlignment: "center",
      verticalAlignment: "center",
      wrapText: true,
      rowHeight: 28,
    };

    let cursor = 4;
    for (const table of tables) {
      if (table.name) {
        sheet.mergeCells(`A${cursor}:${lastColumn}${cursor}`);
        sheet.getRange(`A${cursor}`).values = [[table.name]];
        sheet.getRange(`A${cursor}:${lastColumn}${cursor}`).format = {
          fill: "#EAF0F6",
          font: { bold: true, color: "#264A73", size: 10, name: "Arial Unicode MS" },
        };
        cursor += 1;
      }
      const headers = table.headers ?? [];
      const rows = table.rows ?? [];
      if (!headers.length) continue;
      const tableLast = columnLetter(headers.length - 1);
      sheet.getRange(`A${cursor}:${tableLast}${cursor}`).values = [headers];
      sheet.getRange(`A${cursor}:${tableLast}${cursor}`).format = {
        fill: "#264A73",
        font: { bold: true, color: "#FFFFFF", size: 9, name: "Arial Unicode MS" },
        horizontalAlignment: "center",
        verticalAlignment: "center",
        wrapText: true,
      };
      if (rows.length) {
        const start = cursor + 1;
        const end = cursor + rows.length;
        sheet.getRange(`A${start}:${tableLast}${end}`).values = rows.map((row) => {
          const normalized = [...row];
          while (normalized.length < headers.length) normalized.push(null);
          return normalized.slice(0, headers.length);
        });
        sheet.getRange(`A${start}:${tableLast}${end}`).format = {
          font: { size: 9, name: "Arial Unicode MS", color: "#233142" },
          verticalAlignment: "center",
          wrapText: true,
          borders: {
            top: { style: "continuous", color: "#AEB9C5" },
            bottom: { style: "continuous", color: "#AEB9C5" },
            left: { style: "continuous", color: "#AEB9C5" },
            right: { style: "continuous", color: "#AEB9C5" },
          },
        };
        const used = sheet.getRange(`A${start}:${tableLast}${end}`);
        used.conditionalFormats.addCustom(
          `=OR(ISNUMBER(SEARCH("不合格",A${start})),ISNUMBER(SEARCH("异常",A${start})))`,
          { fill: "#FCE8E6", font: { color: "#B3261E", bold: true } },
        );
        used.conditionalFormats.addCustom(
          `=OR(ISNUMBER(SEARCH("合格",A${start})),ISNUMBER(SEARCH("闭环",A${start})))`,
          { fill: "#E6F4EA", font: { color: "#137333" } },
        );
      }
      cursor += rows.length + 2;
    }

    const signature = payload.signature_contract ?? {};
    if (signature.data_url) {
      const signatureRow = cursor;
      const textLastColumn = columnLetter(Math.min(2, maxColumns - 1));
      sheet.mergeCells(`A${signatureRow}:${textLastColumn}${signatureRow}`);
      sheet.getRange(`A${signatureRow}`).values = [[
        `电子签署（测试）｜${signature.label ?? "资料验收测试专用章"}`,
      ]];
      sheet.getRange(`A${signatureRow}:${lastColumn}${signatureRow + 3}`).format = {
        fill: "#FFF3F1",
        font: { bold: true, color: "#B3261E", size: 9, name: "Arial Unicode MS" },
        verticalAlignment: "center",
        wrapText: true,
        borders: { preset: "outside", style: "thin", color: "#E6A7A2" },
      };
      sheet.getRange(`A${signatureRow}:${lastColumn}${signatureRow + 3}`).format.rowHeight = 24;
      sheet.images.add({
        dataUrl: signature.data_url,
        anchor: {
          from: { row: signatureRow - 1, col: Math.max(1, maxColumns - 2) },
          extent: { widthPx: 230, heightPx: 92 },
        },
      });
      cursor += 5;
    }

    sheet.getRange(`A1:${lastColumn}${Math.max(cursor, 6)}`).format.autofitColumns();
    for (let column = 0; column < maxColumns; column += 1) {
      const letter = columnLetter(column);
      const currentWidth = sheet.getRange(`${letter}:${letter}`).format.columnWidth;
      if (!currentWidth || currentWidth < 10) {
        sheet.getRange(`${letter}:${letter}`).format.columnWidth = 12;
      } else if (currentWidth > 34) {
        sheet.getRange(`${letter}:${letter}`).format.columnWidth = 34;
      }
    }
    sheet.getRange(`A1:${lastColumn}${Math.max(cursor, 6)}`).format.autofitRows();
    sheet.freezePanes.freezeRows(4);

    await fs.mkdir(previewDir, { recursive: true });
    const preview = await workbook.render({
      sheetName,
      autoCrop: "all",
      scale: 1,
      format: "png",
    });
    await fs.writeFile(
      path.join(previewDir, `${sheetName.replaceAll("/", "_")}.png`),
      new Uint8Array(await preview.arrayBuffer()),
    );
  }

  const formulaErrors = await workbook.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
    options: { useRegex: true, maxResults: 300 },
    summary: "final formula error scan",
  });
  await fs.writeFile(`${outputPath}.inspect.ndjson`, formulaErrors.ndjson ?? "");

  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(outputPath);
}

const [payloadPath, outputPath, previewDir] = process.argv.slice(2);
if (!payloadPath || !outputPath || !previewDir) {
  throw new Error("usage: render_xlsx.mjs <payload.json> <output.xlsx> <preview-dir>");
}
const payload = JSON.parse(await fs.readFile(payloadPath, "utf8"));
await buildWorkbook(payload, outputPath, previewDir);
