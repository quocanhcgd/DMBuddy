// Generate the Vietnamese locale from en.ts using MyMemory machine translation.
// The generated locale keeps the source shape/comments and protects i18next
// placeholders while translating only string literal leaves.
//
// Usage: node scripts/generate-vietnamese-locale.mjs

import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';

const scriptDir = path.dirname(url.fileURLToPath(import.meta.url));
const frontendDir = path.resolve(scriptDir, '..');
const localeDir = path.join(frontendDir, 'src/i18n/locales');
const sourcePath = path.join(localeDir, 'en.ts');
const targetPath = path.join(localeDir, 'vi.ts');
const cachePath = path.join(frontendDir, '.vi-translation-cache.json');
const tsPath = path.join(frontendDir, 'node_modules/typescript/lib/typescript.js');
const tsModule = await import(url.pathToFileURL(tsPath).href);
const ts = tsModule.default ?? tsModule;

const source = fs.readFileSync(sourcePath, 'utf8');
const sourceFile = ts.createSourceFile(sourcePath, source, ts.ScriptTarget.Latest, true);
const leaves = [];

function collect(node, keyPath) {
  if (!ts.isObjectLiteralExpression(node)) return;
  for (const prop of node.properties) {
    if (!ts.isPropertyAssignment(prop)) continue;
    const name = ts.isIdentifier(prop.name) || ts.isStringLiteral(prop.name) ? prop.name.text : null;
    if (!name) continue;
    const nextPath = keyPath ? `${keyPath}.${name}` : name;
    if (ts.isObjectLiteralExpression(prop.initializer)) {
      collect(prop.initializer, nextPath);
    } else if (ts.isStringLiteral(prop.initializer) || ts.isNoSubstitutionTemplateLiteral(prop.initializer)) {
      leaves.push({
        key: nextPath,
        value: prop.initializer.text,
        start: prop.initializer.getStart(sourceFile),
        end: prop.initializer.getEnd(),
        quote: prop.initializer.getText(sourceFile).startsWith('`') ? '`' : prop.initializer.getText(sourceFile)[0],
      });
    }
  }
}

ts.forEachChild(sourceFile, (node) => {
  if (ts.isExportAssignment(node)) collect(node.expression, '');
});

let cache = {};
if (fs.existsSync(cachePath)) {
  try { cache = JSON.parse(fs.readFileSync(cachePath, 'utf8')); } catch { cache = {}; }
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const placeholderRe = /\{\{[^{}]+\}\}/g;

function protect(value) {
  const placeholders = [];
  let text = value.replace(/\r?\n/g, '__PB_NEWLINE__');
  text = text.replace(placeholderRe, (match) => {
    const token = `__PB_PLACEHOLDER_${placeholders.length}__`;
    placeholders.push([token, match]);
    return token;
  });
  return { text, placeholders };
}

function restore(value, placeholders) {
  let text = value.replace(/__PB_NEWLINE__/g, '\n');
  for (const [token, original] of placeholders) {
    text = text.split(token).join(original);
  }
  return text;
}

function hasMatchingPlaceholders(sourceValue, translatedValue) {
  const sourceTokens = [...sourceValue.matchAll(placeholderRe)].map((match) => match[0]).sort();
  const translatedTokens = [...translatedValue.matchAll(placeholderRe)].map((match) => match[0]).sort();
  return JSON.stringify(sourceTokens) === JSON.stringify(translatedTokens);
}

function shouldKeep(value) {
  const trimmed = value.trim();
  if (!trimmed || trimmed.length <= 2) return true;
  if (/^https?:\/\//i.test(trimmed)) return true;
  if (/^[A-Z0-9_./:+#()\- ]+$/.test(trimmed) && !/[a-z]/.test(trimmed)) return true;
  if (/^[\d\s.,:%+/*=<>()\-]+$/.test(trimmed)) return true;
  return false;
}

// Deterministic fallback for rate-limited translation providers. This is
// intentionally conservative: it handles common UI phrases while leaving
// product names, URLs, placeholders and code-like values untouched.
const FALLBACK_PHRASES = [
  ['Are you sure you want to', 'Bạn có chắc muốn'],
  ['Please enter', 'Vui lòng nhập'],
  ['Please select', 'Vui lòng chọn'],
  ['Please fill in', 'Vui lòng điền'],
  ['Failed to', 'Không thể'],
  ['Unable to', 'Không thể'],
  ['No ', 'Không có '],
  ['Not found', 'Không tìm thấy'],
  ['Loading', 'Đang tải'],
  ['Saving', 'Đang lưu'],
  ['Saved', 'Đã lưu'],
  ['Add ', 'Thêm '],
  ['Add', 'Thêm'],
  ['Edit', 'Chỉnh sửa'],
  ['Delete', 'Xóa'],
  ['Remove', 'Xóa'],
  ['Cancel', 'Hủy'],
  ['Close', 'Đóng'],
  ['Save', 'Lưu'],
  ['Create', 'Tạo'],
  ['Update', 'Cập nhật'],
  ['Refresh', 'Làm mới'],
  ['Search', 'Tìm kiếm'],
  ['Filter', 'Lọc'],
  ['Clear', 'Xóa'],
  ['Apply', 'Áp dụng'],
  ['Reset', 'Đặt lại'],
  ['Confirm', 'Xác nhận'],
  ['Settings', 'Cài đặt'],
  ['System', 'Hệ thống'],
  ['Status', 'Trạng thái'],
  ['Name', 'Tên'],
  ['Description', 'Mô tả'],
  ['Printer', 'Máy in'],
  ['Printers', 'Máy in'],
  ['Print', 'In'],
  ['Printing', 'Đang in'],
  ['Queue', 'Hàng đợi'],
  ['Archive', 'Lưu trữ'],
  ['Archives', 'Lưu trữ'],
  ['File', 'Tệp'],
  ['Files', 'Tệp'],
  ['Folder', 'Thư mục'],
  ['Library', 'Thư viện'],
  ['Project', 'Dự án'],
  ['Projects', 'Dự án'],
  ['Material', 'Vật liệu'],
  ['Filament', 'Sợi nhựa'],
  ['Inventory', 'Kho'],
  ['Notifications', 'Thông báo'],
  ['Notification', 'Thông báo'],
  ['Enabled', 'Đã bật'],
  ['Disabled', 'Đã tắt'],
  ['Enable', 'Bật'],
  ['Disable', 'Tắt'],
  ['Connected', 'Đã kết nối'],
  ['Disconnected', 'Đã ngắt kết nối'],
  ['Online', 'Trực tuyến'],
  ['Offline', 'Ngoại tuyến'],
  ['Unknown', 'Không xác định'],
  ['Error', 'Lỗi'],
  ['Warning', 'Cảnh báo'],
  ['Success', 'Thành công'],
  ['Required', 'Bắt buộc'],
  ['Optional', 'Tùy chọn'],
  ['Default', 'Mặc định'],
  ['Loading...', 'Đang tải...'],
  ['Save changes', 'Lưu thay đổi'],
  ['View details', 'Xem chi tiết'],
  ['View all', 'Xem tất cả'],
  ['Start print', 'Bắt đầu in'],
  ['Stop print', 'Dừng in'],
  ['Pause print', 'Tạm dừng in'],
  ['Resume print', 'Tiếp tục in'],
  ['Print started', 'Đã bắt đầu in'],
  ['Print completed', 'Đã in xong'],
  ['Print failed', 'In thất bại'],
  ['Authentication', 'Xác thực'],
  ['Password', 'Mật khẩu'],
  ['Username', 'Tên người dùng'],
  ['Login', 'Đăng nhập'],
  ['Logout', 'Đăng xuất'],
  ['Language', 'Ngôn ngữ'],
  ['Today', 'Hôm nay'],
  ['Tomorrow', 'Ngày mai'],
  ['minutes', 'phút'],
  ['hours', 'giờ'],
  ['days', 'ngày'],
];

function fallbackTranslate(value) {
  if (shouldKeep(value)) return value;
  const { text, placeholders } = protect(value);
  let result = text;
  for (const [from, to] of FALLBACK_PHRASES.sort((a, b) => b[0].length - a[0].length)) {
    result = result.replaceAll(from, to);
  }
  // If no phrase matched, mark the string as Vietnamese context rather than
  // silently shipping a value that looks translated but is still English.
  if (result === text) result = `Bản dịch: ${result}`;
  return restore(result, placeholders);
}

async function translateOne(value) {
  if (shouldKeep(value)) return value;
  if (cache[value] && hasMatchingPlaceholders(value, cache[value])) return cache[value];

  if (process.env.SKIP_REMOTE_TRANSLATION === '1') {
    const result = fallbackTranslate(value);
    cache[value] = result;
    return result;
  }

  return fallbackTranslate(value);
}

const uniqueValues = [...new Set(leaves.map((leaf) => leaf.value))];
const pendingValues = uniqueValues.filter((value) =>
  !shouldKeep(value) && (!cache[value] || cache[value].startsWith('Bản dịch:') || !hasMatchingPlaceholders(value, cache[value])),
);
let translatedCount = uniqueValues.length - pendingValues.length;
for (let offset = 0; offset < pendingValues.length;) {
  const batch = [];
  let chars = 0;
  while (offset < pendingValues.length && batch.length < 20) {
    const value = pendingValues[offset];
    if (batch.length > 0 && chars + value.length > 1200) break;
    batch.push(value);
    chars += value.length + 1;
    offset += 1;
  }

  const protectedValues = batch.map((value) => ({ value, ...protect(value) }));
  const text = protectedValues.map((item) => item.text).join('\n');
  try {
    const query = new URLSearchParams({ client: 'dict-chrome-ex', sl: 'en', tl: 'vi', q: text });
    const response = await fetch(`https://clients5.google.com/translate_a/t?${query.toString()}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    const translatedLines = Array.isArray(payload) && typeof payload[0] === 'string'
      ? payload[0].split('\n')
      : [];
    if (translatedLines.length !== protectedValues.length) throw new Error('line count mismatch');

    protectedValues.forEach((item, index) => {
      const result = restore(translatedLines[index], item.placeholders);
      cache[item.value] = hasMatchingPlaceholders(item.value, result)
        ? result
        : fallbackTranslate(item.value);
    });
  } catch (error) {
    console.warn(`[vi] batch fallback (${error})`);
    for (const value of batch) cache[value] = fallbackTranslate(value);
  }

  translatedCount += batch.length;
  fs.writeFileSync(cachePath, JSON.stringify(cache, null, 2), 'utf8');
  console.log(`[vi] translated ${translatedCount}/${uniqueValues.length}`);
  await sleep(100);
}
fs.writeFileSync(cachePath, JSON.stringify(cache, null, 2), 'utf8');

function quote(value, quoteStyle) {
  if (quoteStyle === '`') {
    return `\`${value.replaceAll('\\', '\\\\').replaceAll('`', '\\`').replaceAll('${', '\\${')}\``;
  }
  return `'${value.replaceAll('\\', '\\\\').replaceAll('\r', '\\r').replaceAll('\n', '\\n').replaceAll("'", "\\'")}'`;
}

let output = source;
for (const leaf of [...leaves].sort((a, b) => b.start - a.start)) {
  output = output.slice(0, leaf.start) + quote(cache[leaf.value] ?? leaf.value, leaf.quote) + output.slice(leaf.end);
}
fs.writeFileSync(targetPath, output, 'utf8');
console.log(`[vi] wrote ${targetPath} with ${leaves.length} keys from ${uniqueValues.length} unique strings`);

