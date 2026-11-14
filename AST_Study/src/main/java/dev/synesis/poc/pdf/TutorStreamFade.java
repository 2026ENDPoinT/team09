package dev.synesis.poc.pdf;

import java.util.ArrayDeque;
import java.util.HashMap;
import java.util.Map;

/** Colors only newly visible glyphs, leaving HTML markup intact. */
final class TutorStreamFade {
    private static final int MAX_RECENT_GLYPHS = 512;
    private record Birth(int position, long atMs) {}
    private final ArrayDeque<Birth> recent = new ArrayDeque<>();
    private final int backgroundRgb;
    private final int foregroundRgb;
    private final long durationMs;
    private final boolean softCurve;
    private int visibleGlyphs;

    TutorStreamFade() { this(0x343944, 0xf3f5f9); }

    TutorStreamFade(int backgroundRgb, int foregroundRgb) {
        this(backgroundRgb,foregroundRgb,240,false);
    }

    TutorStreamFade(int backgroundRgb,int foregroundRgb,long durationMs,boolean softCurve) {
        if(durationMs<=0)throw new IllegalArgumentException("Fade duration must be positive");
        this.backgroundRgb = backgroundRgb;
        this.foregroundRgb = foregroundRgb;
        this.durationMs=durationMs;
        this.softCurve=softCurve;
    }

    void reset() {
        recent.clear();
        visibleGlyphs = 0;
    }

    void accept(String html, long nowMs) {
        int count = glyphCount(html);
        if (count < visibleGlyphs) {
            // Markdown can reflow earlier text when a delimiter is completed.
            // Avoid flashing the entire answer in that case.
            recent.clear();
            visibleGlyphs = count;
            return;
        }
        for (int position = Math.max(visibleGlyphs, count - MAX_RECENT_GLYPHS); position < count; position++) {
            recent.addLast(new Birth(position, nowMs));
        }
        visibleGlyphs = count;
        prune(nowMs);
    }

    boolean active(long nowMs) {
        prune(nowMs);
        return !recent.isEmpty();
    }

    /** Initial HTML/math layout can be slow; start fresh glyph fades when paint is ready. */
    void readyToPaint(long acceptedAtMs,long readyAtMs) {
        if(readyAtMs<=acceptedAtMs)return;
        var updated=new ArrayDeque<Birth>();
        for(Birth birth:recent)updated.addLast(birth.atMs==acceptedAtMs?new Birth(birth.position,readyAtMs):birth);
        recent.clear();recent.addAll(updated);
    }

    String decorate(String html, long nowMs) {
        prune(nowMs);
        if (recent.isEmpty()) return html;
        Map<Integer, String> colors = new HashMap<>();
        for (Birth birth : recent) {
            double progress = Math.min(1.0, Math.max(0.0, (nowMs - birth.atMs) / (double) durationMs));
            // Smootherstep eases both ends: no abrupt initial brightening or final snap.
            double opacity = softCurve?progress*progress*progress*(progress*(progress*6-15)+10)
                :progress*(2.0-progress);
            int red = blend((backgroundRgb >> 16) & 0xff, (foregroundRgb >> 16) & 0xff, opacity);
            int green = blend((backgroundRgb >> 8) & 0xff, (foregroundRgb >> 8) & 0xff, opacity);
            int blue = blend(backgroundRgb & 0xff, foregroundRgb & 0xff, opacity);
            colors.put(birth.position, String.format("#%02x%02x%02x", red, green, blue));
        }
        StringBuilder result = new StringBuilder(html.length() + colors.size() * 31);
        int position = 0;
        for (int index = 0; index < html.length();) {
            if (html.charAt(index) == '<') {
                int end = html.indexOf('>', index + 1);
                if (end >= 0) {
                    result.append(html, index, end + 1);
                    index = end + 1;
                    continue;
                }
            }
            int end = glyphEnd(html, index);
            String color = colors.get(position++);
            if (color != null) result.append("<font color=\"").append(color).append("\">");
            result.append(html, index, end);
            if (color != null) result.append("</font>");
            index = end;
        }
        return result.toString();
    }

    private static int glyphCount(String html) {
        int count = 0;
        for (int index = 0; index < html.length();) {
            if (html.charAt(index) == '<') {
                int end = html.indexOf('>', index + 1);
                if (end >= 0) { index = end + 1; continue; }
            }
            count++;
            index = glyphEnd(html, index);
        }
        return count;
    }

    private static int glyphEnd(String html, int index) {
        if (html.charAt(index) == '&') {
            int end = html.indexOf(';', index + 1);
            if (end > index && end - index <= 12) return end + 1;
        }
        return index + Character.charCount(html.codePointAt(index));
    }

    private static int blend(int start, int end, double opacity) {
        return (int) Math.round(start + (end - start) * opacity);
    }

    private void prune(long nowMs) {
        while (!recent.isEmpty() && nowMs - recent.peekFirst().atMs >= durationMs) recent.removeFirst();
    }
}
