import type { ReactNode } from 'react';
import { Alert, Empty, Spin } from 'antd';
import { ApiError } from '../api/client';

/** Uniform loading / error / empty handling for a React Query result. */
export function QueryState({
  isLoading,
  error,
  isEmpty,
  emptyText = '데이터가 없습니다.',
  children,
}: {
  isLoading: boolean;
  error: unknown;
  isEmpty?: boolean;
  emptyText?: ReactNode;
  children: ReactNode;
}) {
  if (isLoading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 48 }}>
        <Spin />
      </div>
    );
  }
  if (error) {
    const message =
      error instanceof ApiError
        ? `[${error.code}] ${error.message}`
        : error instanceof Error
          ? error.message
          : '알 수 없는 오류가 발생했습니다.';
    return <Alert type="error" showIcon message="요청 실패" description={message} />;
  }
  if (isEmpty) {
    return <Empty description={emptyText} image={Empty.PRESENTED_IMAGE_SIMPLE} />;
  }
  return <>{children}</>;
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return `[${error.code}] ${error.message}`;
  if (error instanceof Error) return error.message;
  return '알 수 없는 오류가 발생했습니다.';
}
