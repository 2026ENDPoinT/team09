package dev.synesis.poc.ui;

import java.awt.Graphics;
import javax.swing.text.Caret;
import javax.swing.text.DefaultCaret;
import javax.swing.text.JTextComponent;

/** Keeps text selection and keyboard copy without an insertion bar in reading surfaces. */
public class ReadOnlyCaret extends DefaultCaret {
    @Override public void setVisible(boolean visible) {
        JTextComponent text=getComponent();
        super.setVisible(visible&&text!=null&&text.isEditable());
    }
    @Override public void paint(Graphics graphics) {
        JTextComponent text=getComponent();
        if(text!=null&&text.isEditable())super.paint(graphics);
    }
    public static void applyTo(JTextComponent text) {
        Caret previous=text.getCaret();
        if(previous instanceof ReadOnlyCaret)return;
        ReadOnlyCaret caret=new ReadOnlyCaret();
        int dot=previous.getDot(),mark=previous.getMark();boolean selected=previous.isSelectionVisible();
        caret.setBlinkRate(previous.getBlinkRate());
        if(previous instanceof DefaultCaret original)caret.setUpdatePolicy(original.getUpdatePolicy());
        text.setCaret(caret);
        caret.setDot(mark);caret.moveDot(dot);caret.setSelectionVisible(selected);
        caret.setVisible(false);
    }
}
