'use client';

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

/** MSG-02 Markdown + 멘션 하이라이트 (`@name` → mention: 링크 → span.mention) */
export function Markdown({ text, className }: { text: string; className?: string }) {
  const withMentions = text.replace(/(^|[\s(])@([\p{L}\p{N}_.-]+)/gu, (_m, pre: string, name: string) => `${pre}[@${name}](mention:${encodeURIComponent(name)})`);
  return (
    <div className={`prose-chat text-[14px] leading-[1.55] ${className ?? ''}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children, ...rest }) => {
            if (href?.startsWith('mention:')) return <span className="mention">{children}</span>;
            return (
              <a href={href} target="_blank" rel="noreferrer" {...rest}>
                {children}
              </a>
            );
          },
        }}
      >
        {withMentions}
      </ReactMarkdown>
    </div>
  );
}
