package dev.synesis.poc.pdf;

import dev.synesis.poc.ui.SmoothScrollPane;
import java.awt.Color;
import java.awt.Component;
import java.awt.Point;

/** Shared precise input/handoff, with quiz-only opaque pixel reuse. No animation timer or image cache. */
class QuizScrollPane extends SmoothScrollPane {
    QuizScrollPane(Component view,int verticalPolicy,int horizontalPolicy) {
        super(view,verticalPolicy,horizontalPolicy);
        setOpaque(true);setBackground(Color.WHITE);
        getViewport().setOpaque(true);getViewport().setBackground(Color.WHITE);
        setVerticalScrollReuseEnabled(true);
    }
    void scrollToTop(){resetWheelInput();getViewport().setViewPosition(new Point(0,0));}
}
