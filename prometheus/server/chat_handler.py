#!/usr/bin/env python3
"""
Chat Handler for Memex Prometheus Server

Manages chat sessions with Claude API, streams responses via SSE,
and supports page generation with the Moria theme.
"""

import asyncio
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

import anthropic
import markdown

logger = logging.getLogger(__name__)


class ChatSession:
    """A single chat session with message history."""

    def __init__(self, instance_name: str):
        self.id = str(uuid.uuid4())
        self.instance_name = instance_name
        self.messages: List[Dict[str, Any]] = []
        self.created_at = time.time()
        self.last_active = time.time()

    def add_user_message(self, content: str):
        self.messages.append({"role": "user", "content": content})
        self.last_active = time.time()

    def add_assistant_message(self, content: Any):
        self.messages.append({"role": "assistant", "content": content})
        self.last_active = time.time()

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.last_active) > 3600  # 1 hour TTL


class ChatHandler:
    """Manages chat sessions and Claude API interactions."""

    def __init__(self, instance_manager, pages_dir: str = "/ssd/memex/pages"):
        self.instance_manager = instance_manager
        self.pages_dir = Path(pages_dir)
        self.pages_dir.mkdir(parents=True, exist_ok=True)
        self.sessions: Dict[str, ChatSession] = {}

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            logger.warning("ANTHROPIC_API_KEY not set - chat will not work")
            self.client = None
        else:
            self.client = anthropic.Anthropic(api_key=api_key)

        # Load page template
        template_path = Path(__file__).parent / "page_template.html"
        if template_path.exists():
            self.page_template = template_path.read_text()
        else:
            logger.warning("page_template.html not found")
            self.page_template = "<html><body>{content}</body></html>"

    def _cleanup_sessions(self):
        """Remove expired sessions."""
        expired = [sid for sid, s in self.sessions.items() if s.is_expired]
        for sid in expired:
            del self.sessions[sid]
        if expired:
            logger.info(f"Cleaned up {len(expired)} expired chat sessions")

    def get_or_create_session(self, session_id: Optional[str], instance_name: str) -> ChatSession:
        """Get existing session or create new one."""
        self._cleanup_sessions()
        if session_id and session_id in self.sessions:
            session = self.sessions[session_id]
            session.last_active = time.time()
            return session
        session = ChatSession(instance_name)
        self.sessions[session.id] = session
        return session

    def delete_session(self, session_id: str) -> bool:
        if session_id in self.sessions:
            del self.sessions[session_id]
            return True
        return False

    def _get_system_prompt(self, instance_name: str, cross_instance: bool = False) -> str:
        if cross_instance:
            instances = self.instance_manager.list_instances()
            return (
                "You are Memex, an AI assistant with access to screen capture history across multiple instances: "
                f"{', '.join(instances)}. "
                "You can search OCR text from screenshots, view activity patterns, generate summaries, "
                "and create standalone web pages. Each tool is prefixed with the instance it operates on. "
                "When asked about activity across instances, query each relevant instance separately and synthesize. "
                "When referencing screenshots, include the screenshot_path if available in results. "
                "You can generate pages using the generate_page tool to create standalone Moria-themed HTML pages."
            )
        return (
            f"You are Memex, an AI assistant with access to screen capture history for the '{instance_name}' instance. "
            "You can search OCR text from screenshots, view activity patterns, generate daily summaries, "
            "and create standalone web pages. "
            "When you find relevant results, mention timestamps and screen names to help the user understand context. "
            "If results include screenshot_path, reference it so the UI can display thumbnails. "
            "You can generate pages using the generate_page tool to create standalone Moria-themed HTML pages "
            "with embedded content and screenshots."
        )

    def _get_tools_for_instance(self, instance_name: str) -> List[Dict[str, Any]]:
        """Build Claude tool definitions from instance's MCP tools plus generate_page."""
        inst = self.instance_manager.get_instance(instance_name)
        if not inst:
            return []

        tools = []
        for tool_def in inst.get_tool_definitions():
            # Convert MCP tool format to Claude tool format
            tools.append({
                "name": tool_def["name"],
                "description": tool_def["description"],
                "input_schema": tool_def["inputSchema"],
            })

        # Add generate_page tool
        tools.append({
            "name": "generate_page",
            "description": "Generate a standalone Moria-themed HTML page. Use this to create wiki entries, blog posts, workflow docs, or any content the user wants as a shareable page.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Page title"},
                    "content_markdown": {"type": "string", "description": "Page content in Markdown format"},
                    "screenshot_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of screenshot filenames to embed in the page",
                    },
                },
                "required": ["title", "content_markdown"],
            },
        })

        return tools

    def _get_cross_instance_tools(self) -> List[Dict[str, Any]]:
        """Build tools for cross-instance chat, prefixed by instance name."""
        tools = []
        for inst_name in self.instance_manager.list_instances():
            inst = self.instance_manager.get_instance(inst_name)
            if not inst:
                continue
            for tool_def in inst.get_tool_definitions():
                tools.append({
                    "name": f"{inst_name}__{tool_def['name']}",
                    "description": f"[{inst_name.upper()}] {tool_def['description']}",
                    "input_schema": tool_def["inputSchema"],
                })

        # Add generate_page (shared)
        tools.append({
            "name": "generate_page",
            "description": "Generate a standalone Moria-themed HTML page with content and embedded screenshots.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Page title"},
                    "content_markdown": {"type": "string", "description": "Page content in Markdown format"},
                    "screenshot_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of screenshot filenames to embed",
                    },
                },
                "required": ["title", "content_markdown"],
            },
        })

        return tools

    def _slugify(self, title: str) -> str:
        slug = title.lower().strip()
        slug = re.sub(r'[^\w\s-]', '', slug)
        slug = re.sub(r'[\s_]+', '-', slug)
        slug = re.sub(r'-+', '-', slug)
        return slug[:80].strip('-')

    def generate_page(self, title: str, content_markdown: str,
                      screenshot_paths: Optional[List[str]] = None,
                      instance_name: str = "") -> Dict[str, Any]:
        """Generate a standalone Moria-themed HTML page."""
        md_extensions = ['tables', 'fenced_code', 'codehilite', 'toc', 'nl2br']
        content_html = markdown.markdown(content_markdown, extensions=md_extensions)

        # Embed screenshot images if referenced
        if screenshot_paths:
            screenshots_html = ""
            for path in screenshot_paths:
                filename = Path(path).name
                # Try to extract timestamp from filename for caption
                caption = filename.replace('.png', '').replace('.jpg', '').replace('_', ' ')
                img_src = f"/screenshots/{instance_name}/{filename}" if instance_name else f"/screenshots/{filename}"
                screenshots_html += (
                    f'<figure class="screenshot">'
                    f'<img src="{img_src}" alt="{caption}" loading="lazy">'
                    f'<figcaption>{caption}</figcaption>'
                    f'</figure>\n'
                )
            content_html += f'\n<div class="screenshots-gallery">{screenshots_html}</div>'

        now = datetime.now()
        page_html = self.page_template.replace("{{title}}", title)
        page_html = page_html.replace("{{content}}", content_html)
        page_html = page_html.replace("{{date}}", now.strftime("%B %d, %Y"))
        page_html = page_html.replace("{{timestamp}}", now.isoformat())
        page_html = page_html.replace("{{instance}}", instance_name)

        slug = self._slugify(title)
        # Avoid collision
        page_path = self.pages_dir / f"{slug}.html"
        counter = 1
        while page_path.exists():
            page_path = self.pages_dir / f"{slug}-{counter}.html"
            counter += 1

        page_path.write_text(page_html)
        final_slug = page_path.stem

        logger.info(f"Generated page: {final_slug} ({len(page_html)} bytes)")

        return {
            "url": f"/pages/{final_slug}",
            "title": title,
            "slug": final_slug,
            "size_bytes": len(page_html),
        }

    async def chat(self, session: ChatSession, user_message: str,
                   cross_instance: bool = False) -> AsyncGenerator[str, None]:
        """Stream chat response as SSE events."""
        if not self.client:
            yield f"event: error\ndata: {json.dumps({'error': 'ANTHROPIC_API_KEY not configured'})}\n\n"
            return

        session.add_user_message(user_message)
        instance_name = session.instance_name

        system_prompt = self._get_system_prompt(instance_name, cross_instance)
        if cross_instance:
            tools = self._get_cross_instance_tools()
        else:
            tools = self._get_tools_for_instance(instance_name)

        messages = session.messages.copy()

        # Tool use loop — Claude may call tools multiple times
        max_iterations = 10
        for iteration in range(max_iterations):
            try:
                response = self.client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=4096,
                    system=system_prompt,
                    tools=tools,
                    messages=messages,
                    stream=True,
                )
            except anthropic.APIError as e:
                yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
                return

            # Collect the full response for message history
            assistant_content = []
            current_text = ""
            current_tool_use = None

            for event in response:
                if event.type == "content_block_start":
                    if event.content_block.type == "text":
                        current_text = ""
                    elif event.content_block.type == "tool_use":
                        current_tool_use = {
                            "id": event.content_block.id,
                            "name": event.content_block.name,
                            "input": "",
                        }
                        yield f"event: tool_call\ndata: {json.dumps({'name': event.content_block.name, 'id': event.content_block.id})}\n\n"

                elif event.type == "content_block_delta":
                    if hasattr(event.delta, "text"):
                        current_text += event.delta.text
                        yield f"event: text\ndata: {json.dumps({'text': event.delta.text})}\n\n"
                    elif hasattr(event.delta, "partial_json"):
                        if current_tool_use:
                            current_tool_use["input"] += event.delta.partial_json

                elif event.type == "content_block_stop":
                    if current_text:
                        assistant_content.append({"type": "text", "text": current_text})
                        current_text = ""
                    if current_tool_use:
                        try:
                            parsed_input = json.loads(current_tool_use["input"]) if current_tool_use["input"] else {}
                        except json.JSONDecodeError:
                            parsed_input = {}
                        assistant_content.append({
                            "type": "tool_use",
                            "id": current_tool_use["id"],
                            "name": current_tool_use["name"],
                            "input": parsed_input,
                        })
                        current_tool_use = None

                elif event.type == "message_stop":
                    pass

                elif event.type == "message_delta":
                    stop_reason = getattr(event.delta, "stop_reason", None)

            # Check if we need to handle tool calls
            tool_calls = [b for b in assistant_content if b["type"] == "tool_use"]

            if not tool_calls:
                # No tool calls — done
                session.add_assistant_message(assistant_content)
                yield "event: done\ndata: {}\n\n"
                return

            # Add assistant message to conversation
            messages.append({"role": "assistant", "content": assistant_content})

            # Execute tool calls and add results
            tool_results = []
            for tc in tool_calls:
                tool_name = tc["name"]
                tool_input = tc["input"]
                tool_id = tc["id"]

                try:
                    result = await self._execute_tool(
                        tool_name, tool_input, instance_name, cross_instance
                    )
                    result_str = json.dumps(result, default=str)
                    yield f"event: tool_result\ndata: {json.dumps({'id': tool_id, 'name': tool_name, 'result_preview': result_str[:200]})}\n\n"

                    # Check if page was generated
                    if tool_name == "generate_page" and "url" in result:
                        yield f"event: page_created\ndata: {json.dumps({'url': result['url'], 'title': result['title']})}\n\n"

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": result_str,
                    })
                except Exception as e:
                    logger.error(f"Error executing tool {tool_name}: {e}")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": json.dumps({"error": str(e)}),
                        "is_error": True,
                    })

            messages.append({"role": "user", "content": tool_results})

        # If we exhausted iterations
        session.add_assistant_message(assistant_content)
        yield "event: done\ndata: {}\n\n"

    async def _execute_tool(self, tool_name: str, tool_input: Dict[str, Any],
                            instance_name: str, cross_instance: bool) -> Any:
        """Execute a tool call, routing to the right instance."""
        if tool_name == "generate_page":
            return self.generate_page(
                title=tool_input["title"],
                content_markdown=tool_input["content_markdown"],
                screenshot_paths=tool_input.get("screenshot_paths"),
                instance_name=instance_name,
            )

        if cross_instance and "__" in tool_name:
            # Cross-instance tool: format is "instance__tool-name"
            parts = tool_name.split("__", 1)
            target_instance = parts[0]
            actual_tool = parts[1]
            inst = self.instance_manager.get_instance(target_instance)
            if not inst:
                raise ValueError(f"Unknown instance: {target_instance}")
            return await inst.call_tool(actual_tool, tool_input)

        # Single-instance tool
        inst = self.instance_manager.get_instance(instance_name)
        if not inst:
            raise ValueError(f"Unknown instance: {instance_name}")
        return await inst.call_tool(tool_name, tool_input)
