import type { BatchDraftItem } from './api';
export type { BatchDraftItem } from './api';

export type BatchLanguage = BatchDraftItem['language_id'];

export interface BatchRowError {
  index: number;
  line: number;
  field: string;
  message: string;
}

export interface BatchParseResult {
  items: BatchDraftItem[];
  errors: BatchRowError[];
}

interface CsvRecord {
  values: string[];
  line: number;
}

const REQUIRED_FIELDS = ['problem_id', 'language_id', 'source_code'] as const;

export function inferLanguageFromFilename(filename: string): BatchLanguage | null {
  const extension = filename.split('.').pop()?.toLowerCase();
  if (extension === 'py') return 'python3';
  if (extension === 'cpp' || extension === 'cc') return 'cpp17';
  return null;
}

export function parseBatchInput(contents: string, filename: string): BatchParseResult {
  const extension = filename.split('.').pop()?.toLowerCase();
  if (extension === 'jsonl') return parseJsonl(contents);
  if (extension === 'json') return parseJson(contents);
  if (extension === 'csv') return parseCsv(contents);
  return {
    items: [],
    errors: [{ index: -1, line: 1, field: 'file', message: 'Choose a .jsonl, .json, or .csv file' }],
  };
}

export function parseJsonl(contents: string): BatchParseResult {
  const records: Array<{ value: unknown; line: number; index: number }> = [];
  const errors: BatchRowError[] = [];
  let rowIndex = 0;
  contents.split(/\r?\n/).forEach((line, index) => {
    if (!line.trim()) return;
    const currentIndex = rowIndex;
    rowIndex += 1;
    try {
      records.push({ value: JSON.parse(line) as unknown, line: index + 1, index: currentIndex });
    } catch (error) {
      errors.push({
        index: currentIndex,
        line: index + 1,
        field: 'json',
        message: error instanceof Error ? error.message : 'Invalid JSON',
      });
    }
  });
  return parseRecords(
    records.map(({ value, line }) => ({ value, line })),
    errors,
    records.map(({ index }) => index),
  );
}

export function validateBatchItems(values: unknown[]): BatchParseResult {
  return parseRecords(values.map((value, index) => ({ value, line: index + 1 })), []);
}

function parseJson(contents: string): BatchParseResult {
  let value: unknown;
  try {
    value = JSON.parse(contents) as unknown;
  } catch (error) {
    return {
      items: [],
      errors: [{
        index: 0,
        line: 1,
        field: 'json',
        message: error instanceof Error ? error.message : 'Invalid JSON',
      }],
    };
  }
  const records = Array.isArray(value)
    ? value
    : isRecord(value) && Array.isArray(value.items)
      ? value.items
      : null;
  if (!records) {
    return {
      items: [],
      errors: [{ index: 0, line: 1, field: 'items', message: 'JSON must be an array or contain an items array' }],
    };
  }
  return parseRecords(records.map((record, index) => ({ value: record, line: index + 1 })), []);
}

function parseCsv(contents: string): BatchParseResult {
  const parsed = readCsvRecords(contents);
  if (parsed.errors.length) return { items: [], errors: parsed.errors };
  if (!parsed.records.length) {
    return { items: [], errors: [{ index: -1, line: 1, field: 'file', message: 'CSV file is empty' }] };
  }
  const headers = parsed.records[0].values.map((header) => header.trim());
  const missing = REQUIRED_FIELDS.filter((field) => !headers.includes(field));
  if (missing.length) {
    return {
      items: [],
      errors: missing.map((field) => ({
        index: -1,
        line: parsed.records[0].line,
        field,
        message: `CSV is missing the ${field} column`,
      })),
    };
  }
  const rows = parsed.records.slice(1).map((record, index) => ({
    value: Object.fromEntries(headers.map((header, column) => [header, record.values[column] ?? ''])),
    line: record.line,
    index,
  }));
  return parseRecords(rows.map(({ value, line }) => ({ value, line })), [], rows.map((row) => row.index));
}

function readCsvRecords(contents: string): { records: CsvRecord[]; errors: BatchRowError[] } {
  const records: CsvRecord[] = [];
  const errors: BatchRowError[] = [];
  let values: string[] = [];
  let field = '';
  let quoted = false;
  let line = 1;
  let recordLine = 1;
  const finishField = () => {
    values.push(field);
    field = '';
  };
  const finishRecord = () => {
    finishField();
    if (values.some((value) => value.length > 0)) records.push({ values, line: recordLine });
    values = [];
    recordLine = line;
  };

  for (let index = 0; index < contents.length; index += 1) {
    const character = contents[index];
    if (quoted) {
      if (character === '"' && contents[index + 1] === '"') {
        field += '"';
        index += 1;
      } else if (character === '"') {
        quoted = false;
      } else {
        field += character;
        if (character === '\n') line += 1;
      }
      continue;
    }
    if (character === '"' && field.length === 0) {
      quoted = true;
    } else if (character === ',') {
      finishField();
    } else if (character === '\n') {
      line += 1;
      finishRecord();
    } else if (character !== '\r') {
      field += character;
    }
  }
  if (quoted) {
    errors.push({
      index: records.length,
      line: recordLine,
      field: 'csv',
      message: 'CSV contains an unterminated quoted field',
    });
  } else if (field.length || values.length) {
    finishRecord();
  }
  return { records, errors };
}

function parseRecords(
  records: Array<{ value: unknown; line: number }>,
  initialErrors: BatchRowError[],
  rowIndexes?: number[],
): BatchParseResult {
  const items: BatchDraftItem[] = [];
  const errors = [...initialErrors];
  records.forEach(({ value, line }, recordIndex) => {
    const index = rowIndexes?.[recordIndex] ?? recordIndex;
    if (!isRecord(value)) {
      errors.push({ index, line, field: 'item', message: 'Each row must be an object' });
      return;
    }
    const item = {} as BatchDraftItem;
    const rawProblemId = value.problem_id;
    const problemId = typeof rawProblemId === 'number' ? rawProblemId : Number(rawProblemId);
    if (!Number.isInteger(problemId) || problemId < 1) {
      errors.push({ index, line, field: 'problem_id', message: 'Must be a positive integer' });
    } else {
      item.problem_id = problemId;
    }

    if (value.language_id !== 'python3' && value.language_id !== 'cpp17') {
      errors.push({ index, line, field: 'language_id', message: 'Must be python3 or cpp17' });
    } else {
      item.language_id = value.language_id;
    }

    if (typeof value.source_code !== 'string' || value.source_code.length === 0) {
      errors.push({ index, line, field: 'source_code', message: 'Must be a non-empty string' });
    } else if (new TextEncoder().encode(value.source_code).length > 64 * 1024) {
      errors.push({ index, line, field: 'source_code', message: 'Must not exceed 64 KB' });
    } else {
      item.source_code = value.source_code;
    }

    if (value.sample_id !== undefined && value.sample_id !== null) {
      if (typeof value.sample_id !== 'string' || value.sample_id.length > 255) {
        errors.push({ index, line, field: 'sample_id', message: 'Must be a string of at most 255 characters' });
      } else {
        item.sample_id = value.sample_id;
      }
    }
    if (!errors.some((error) => error.index === index)) items.push(item);
  });
  if (!records.length && !errors.length) {
    errors.push({ index: -1, line: 1, field: 'items', message: 'No submissions found' });
  }
  return { items, errors };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

const PYTHON_VARIANTS = [
  `import sys
print(sum(map(int, sys.stdin.read().split())))`,
  `a, b = map(int, input().split())
print(a + b)`,
  `values = list(map(int, input().split()))
print(values[0] + values[1])`,
  'print(sum(int(value) for value in input().split()))',
];

const CPP_VARIANTS = [
  `#include <iostream>
int main() { long long a, b; std::cin >> a >> b; std::cout << a + b << '\\n'; }`,
  `#include <iostream>
using namespace std;
int main() { int a, b; if (cin >> a >> b) cout << (a + b) << endl; }`,
];

export function createDemoBatch(problemId: number): BatchDraftItem[] {
  const items: BatchDraftItem[] = [];
  const add = (
    count: number,
    verdict: string,
    language: BatchLanguage,
    source: string | string[],
  ): void => {
    for (let index = 0; index < count; index += 1) {
      items.push({
        problem_id: problemId,
        language_id: language,
        source_code: Array.isArray(source) ? source[index % source.length] : source,
        sample_id: `demo-${verdict}-${String(index + 1).padStart(2, '0')}`,
      });
    }
  };
  add(50, 'AC-PY', 'python3', PYTHON_VARIANTS);
  add(20, 'AC-CPP', 'cpp17', CPP_VARIANTS);
  add(20, 'WA', 'python3', 'print(0)');
  add(10, 'RE', 'python3', "raise RuntimeError('demo runtime error')");
  add(10, 'TLE', 'python3', `while True:
    pass`);
  add(10, 'MLE', 'python3', `data = bytearray(2 * 1024 * 1024 * 1024)
print(0)`);
  return items;
}

export function expectedDemoVerdict(sampleId: string | null | undefined): string | null {
  const match = sampleId?.match(/^demo-(AC|WA|RE|TLE|MLE)(?:-|$)/i);
  return match?.[1]?.toUpperCase() ?? null;
}
