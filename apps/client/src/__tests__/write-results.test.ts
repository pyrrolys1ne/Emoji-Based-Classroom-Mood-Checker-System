import { describe, expect, it } from 'vitest';
import { createApiRepository } from '../repositories';
import { writeResultIsUnknown } from '../models/client';

describe('write result certainty', () => {
  it.each([
    [200, { code: 'OK', data: null }, true],
    [200, { code: 'OK', data: { id: 'placeholder' } }, true],
    [200, 'not-json', true],
    [200, { code: 'ERROR', data: null }, true],
    [502, { code: 'UNAVAILABLE', data: null }, true],
    [503, { code: 'UNAVAILABLE', data: null }, true],
    [501, { code: 'NOT_IMPLEMENTED', data: null }, false],
    [403, { code: 'FORBIDDEN', data: null }, false],
    [422, { code: 'VALIDATION_ERROR', data: null }, false],
  ])('classifies HTTP %s for a non-confirmed submission', async (status, body, unknown) => {
    const fetcher = (async () =>
      new Response(typeof body === 'string' ? body : JSON.stringify(body), {
        status,
      })) as typeof fetch;
    const repo = createApiRepository({ fetcher });
    try {
      await repo.submit('synthetic-token', '11111111-1111-4111-8111-111111111111', 'HAPPY');
      expect.fail('The response must not confirm a saved record');
    } catch (error) {
      expect(writeResultIsUnknown(error)).toBe(unknown);
    }
  });

  it.each([
    { sessionId: 'another-classroom' },
    { emotion: 'SAD' },
    { source: 'AI' },
    { userId: null },
    { confidence: 0.9 },
    { simulated: true },
    { inferenceProvider: 'DeepSeek', confidenceKind: 'self_reported' },
    { student: { id: 'unrelated-student' } },
  ])('keeps an inconsistent success receipt uncertain: %j', async (change) => {
    const sessionId = '11111111-1111-4111-8111-111111111111';
    const data = {
      id: 'saved-record',
      userId: 'student',
      sessionId,
      emotion: 'HAPPY',
      source: 'MANUAL',
      confidence: null,
      recordedAt: '2026-11-06T02:00:00Z',
      ...change,
    };
    const repo = createApiRepository({
      fetcher: (async () => new Response(JSON.stringify({ code: 'OK', data }))) as typeof fetch,
    });
    await expect(repo.submit('token', sessionId, 'HAPPY')).rejects.toMatchObject({
      code: 'INVALID_RESPONSE',
    });
  });
});
