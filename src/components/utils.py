# A log line is a list of (text, color) segments, so a single message can mix colors.
MessageSegment = tuple[str, tuple[int, int, int]]
Message = list[MessageSegment]
