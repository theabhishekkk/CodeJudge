import { describe, expect, it } from 'vitest';
import {
  createDemoBatch,
  expectedDemoVerdict,
  inferLanguageFromFilename,
  parseBatchInput,
  parseJsonl,
} from './batchUtils';

describe('batch input parsing', () => {
  it('parses JSONL and reports row-specific validation failures', () => {
    const parsed = parseJsonl([
      '{"problem_id":1,"language_id":"python3","source_code":"print(1)"}',
      '{"problem_id":0,"language_id":"java","source_code":""}',
    ].join('\n'));

    expect(parsed.items).toHaveLength(1);
    expect(parsed.errors.map(({ index, field }) => [index, field])).toEqual([
      [1, 'problem_id'],
      [1, 'language_id'],
      [1, 'source_code'],
    ]);
  });

  it('parses quoted CSV source code including commas and newlines', () => {
    const parsed = parseBatchInput(
      `problem_id,language_id,source_code,sample_id
1,python3,"print(""a,b"")
print(2)",sample-1
`,
      'samples.csv',
    );

    expect(parsed.errors).toEqual([]);
    expect(parsed.items[0].source_code).toBe('print("a,b")\nprint(2)');
    expect(parsed.items[0].sample_id).toBe('sample-1');
  });

  it('rejects source larger than 64 KiB', () => {
    const parsed = parseJsonl(JSON.stringify({
      problem_id: 1,
      language_id: 'python3',
      source_code: 'x'.repeat(64 * 1024 + 1),
    }));

    expect(parsed.errors).toContainEqual(expect.objectContaining({
      index: 0,
      field: 'source_code',
    }));
    expect(parsed.items).toHaveLength(0);
  });
});

describe('source-file language inference', () => {
  it.each([
    ['answer.py', 'python3'],
    ['folder/Solution.CPP', 'cpp17'],
    ['main.cc', 'cpp17'],
    ['main.java', null],
  ])('infers %s', (filename, language) => {
    expect(inferLanguageFromFilename(filename)).toBe(language);
  });
});

describe('demo batch generator', () => {
  it('generates the requested 120 verdict-labeled samples', () => {
    const items = createDemoBatch(1);
    const counts = items.reduce<Record<string, number>>((result, item) => {
      const expected = expectedDemoVerdict(item.sample_id) ?? 'unknown';
      result[expected] = (result[expected] ?? 0) + 1;
      return result;
    }, {});

    expect(items).toHaveLength(120);
    expect(counts).toEqual({ AC: 70, WA: 20, RE: 10, TLE: 10, MLE: 10 });
    expect(items.filter((item) => item.language_id === 'cpp17')).toHaveLength(20);
    expect(items.find((item) => item.sample_id === 'demo-TLE-03')?.source_code).toContain('while True');
  });
});
