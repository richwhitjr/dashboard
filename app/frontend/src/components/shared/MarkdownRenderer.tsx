import ReactMarkdown from 'react-markdown';
import rehypeSanitize from 'rehype-sanitize';

export function MarkdownRenderer({ content }: { content: string }) {
  return (
    <div className="markdown-content">
      <ReactMarkdown rehypePlugins={[rehypeSanitize]}>{content}</ReactMarkdown>
    </div>
  );
}
