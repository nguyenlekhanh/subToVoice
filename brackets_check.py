try_block = """
        try:
            if new_start_ms < 0:
                new_start_ms = 0
                new_end_ms = new_start_ms + (old_end - old_start)
            if new_end_ms > self.state.video_duration_ms and self.state.video_duration_ms > 0:
                new_end_ms = self.state.video_duration_ms
                new_start_ms = new_end_ms - (old_end - old_start)
            
            if new_start_ms < 0:
                new_start_ms = 0
                new_end_ms = new_start_ms + (old_end - old_start)
            if new_end_ms > self.state.video_duration_ms and self.state.video_duration_ms > 0:
                new_end_ms = self.state.video_duration_ms
                new_start_ms = new_end_ms - (old_end - old_start)
            
            # Ensure valid
            if new_start_ms >= 0 and new_end_ms > new_start_ms:
                self._drag_subtitle.start_ms = new_start_ms
                self._drag_subtitle.end_ms = new_end_ms
                self._rebuild_timeline()
                # Update Treeview
                for item in self.subtitle_tree.get_children():
                    values = self.subtitle_tree.item(item, "values")
                    if int(values[0]) == self._drag_subtitle.index:
                        self.subtitle_tree.set(item, "start", self._format_timestamp_display(new_start_ms))
                        self.subtitle_tree.set(item, "end", self._format_timestamp_display(new_end_ms))
                        break
                self._update_status(f"Moved subtitle {self._drag_subtitle.index}")
        except Exception as e:
            self._update_status(f"Error moving subtitle: {e}")
"""

paren = bracket = brace = 0
for ch in try_block:
    if ch == '(': paren += 1
    elif ch == ')': paren -= 1
    elif ch == '[': bracket += 1
    elif ch == ']': bracket -= 1
    elif ch == '{': brace += 1
    elif ch == '}': brace -= 1

print(f"Parentheses: {paren}")
print(f"Brackets: {bracket}")
print(f"Braces: {brace}")