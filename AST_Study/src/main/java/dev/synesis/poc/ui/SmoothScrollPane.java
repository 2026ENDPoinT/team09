package dev.synesis.poc.ui;

import java.awt.Component;

/** Shared PDF-speed scrolling with the study view's existing edge-mask painting. */
public class SmoothScrollPane extends FadeScrollPane {

    public SmoothScrollPane(Component view) {
        super(view);
    }

    public SmoothScrollPane(Component view, int verticalPolicy, int horizontalPolicy) {
        super(view, verticalPolicy, horizontalPolicy);
    }

}
