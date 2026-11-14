package dev.synesis.poc.ui;

import javax.swing.*;
import java.awt.*;

/** Stores divider proportions independently of Swing's pixel-based layout bookkeeping. */
public final class ProportionalSplitPane extends JSplitPane {
    private double ratio = Double.NaN;
    private boolean layingOut;
    private double monitoredRatio = Double.NaN;
    private String monitoredConfiguration;
    private Object dragRevision;
    private boolean captureAfterTransition;

    /** Poll actual component bounds, accepting a new baseline only after explicit layout changes. */
    public void monitorRatio(String configuration, boolean transitioning) {
        if (!java.util.Objects.equals(configuration, monitoredConfiguration)) {
            monitoredConfiguration = configuration;
            captureAfterTransition = true;
        }
        if (transitioning) { captureAfterTransition = true; return; }
        if (getLeftComponent() == null || getRightComponent() == null || getDividerSize() == 0)
            return;
        int left = getLeftComponent().getWidth(), right = getRightComponent().getWidth();
        if (left + right <= 0 || available() <= 0) return;
        Object revision = getClientProperty("synesis.dividerRevision");
        boolean userDrag = Boolean.TRUE.equals(getClientProperty("synesis.dividerDragging"))
            || !java.util.Objects.equals(revision, dragRevision);
        if (captureAfterTransition || userDrag || Double.isNaN(monitoredRatio)) {
            monitoredRatio = left / (double) (left + right);
            ratio = monitoredRatio;
            dragRevision = revision;
            captureAfterTransition = false;
            return;
        }
        // Keep the desired proportion even when minimum widths temporarily clamp the layout.
        int width = available();
        int target = (int) Math.round(width * monitoredRatio);
        int leftMin = getLeftComponent().getMinimumSize().width;
        int rightMin = getRightComponent().getMinimumSize().width;
        if (width >= leftMin + rightMin)
            target = Math.max(leftMin, Math.min(width - rightMin, target));
        ratio = monitoredRatio;
        if (Math.abs(left - target) > 1) {
            layingOut = true;
            try { super.setDividerLocation(getInsets().left + target); }
            finally { layingOut = false; }
            doLayout();
            revalidate();
            repaint();
        }
    }

    public ProportionalSplitPane(int orientation) { super(orientation); }

    public ProportionalSplitPane(int orientation, Component left, Component right) {
        super(orientation, left, right);
    }

    public ProportionalSplitPane(int orientation, Component left, Component right, double initialRatio) {
        this(orientation, left, right);
        ratio = initialRatio;
    }

    private int available() {
        Insets insets = getInsets();
        return Math.max(0, getWidth() - insets.left - insets.right - getDividerSize());
    }

    @Override public void setDividerLocation(int location) {
        // Explicit changes come from divider dragging or panel opening/closing animations.
        // Never learn a new ratio from the pixel position produced by a resize layout.
        int width = available();
        if (!layingOut && width > 0 && location >= 0) {
            ratio = Math.max(0, Math.min(1,
                (location - getInsets().left) / (double) width));
        }
        super.setDividerLocation(location);
    }

    @Override public void doLayout() {
        if (layingOut) return;
        layingOut = true;
        try {
            int width = available();
            boolean splitVisible = getLeftComponent() != null && getRightComponent() != null
                && getDividerSize() > 0;
            if (splitVisible && width > 0) {
                if (Double.isNaN(ratio)) {
                    int initial = getDividerLocation();
                    ratio = initial < 0 ? .5 : Math.max(0, Math.min(1,
                        (initial - getInsets().left) / (double) width));
                }
                int target = (int) Math.round(width * ratio);
                int leftMinimum = getLeftComponent().getMinimumSize().width;
                int rightMinimum = getRightComponent().getMinimumSize().width;
                if (width >= leftMinimum + rightMinimum)
                    target = Math.max(leftMinimum, Math.min(width - rightMinimum, target));
                super.setDividerLocation(getInsets().left + target);
            }
            super.doLayout();
        } finally { layingOut = false; }
    }
}
