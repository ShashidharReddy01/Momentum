import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ConfigContext } from '@/lib/config';
import { configFixture } from '@/mocks/fixtures';
import { AIBadge, AICallout } from './AI';

function withConfig(aiMock: boolean, ui: React.ReactNode) {
  return render(
    <ConfigContext.Provider value={configFixture({ ai_mock: aiMock })}>{ui}</ConfigContext.Provider>,
  );
}

describe('AI mock marker', () => {
  it('marks AI output in purple while the server answers from mock fixtures', () => {
    withConfig(
      true,
      <>
        <AICallout>Drafted text</AICallout>
        <AIBadge />
      </>,
    );
    expect(screen.getAllByText('Mock')).toHaveLength(2);
    expect(screen.getAllByTitle(/mock mode/i)[0]).toHaveClass('text-mock');
  });

  it('shows nothing extra against a real model', () => {
    withConfig(false, <AICallout>Drafted text</AICallout>);
    expect(screen.queryByText('Mock')).toBeNull();
  });
});
