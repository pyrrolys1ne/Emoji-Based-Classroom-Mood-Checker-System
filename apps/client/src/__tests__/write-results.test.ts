import { describe, expect, it } from 'vitest';
import { createApiRepository } from '../repositories';
import { writeResultIsUnknown } from '../models/client';

describe('write result certainty', () => {
  it.each([
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
});
