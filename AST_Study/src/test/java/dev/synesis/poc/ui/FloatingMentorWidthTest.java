package dev.synesis.poc.ui;

import javax.swing.*;
import java.awt.*;
import java.awt.event.MouseEvent;
import java.lang.reflect.Field;

/** Offscreen geometry: both resize handles share the reading-column width cap. */
public final class FloatingMentorWidthTest {
    public static void main(String[] args) throws Exception {
        SwingUtilities.invokeAndWait(() -> {
            FloatingMentor mentor = new FloatingMentor();
            mentor.setSize(2000, 1200);
            mentor.setContent(new JPanel());
            mentor.setOpen(true, false);
            JComponent card = (JComponent)get(mentor, "card");
            resize(mentor, "southeast", 1400, 100);
            check(card.getWidth() == 962, "southeast resize caps width");
            check(card.getHeight() == 800, "height remains independently resizable");
            resize(mentor, "southeast", -400, 0);
            int right = card.getX() + card.getWidth();
            resize(mentor, "northwest", -1400, 0);
            check(card.getWidth() == 962, "northwest resize caps width");
            check(card.getX() + card.getWidth() == right, "northwest cap preserves the opposite edge");
            mentor.setSize(500, 700);mentor.doLayout();
            check(card.getWidth() <= 468 && card.getX() >= 0 && card.getX()+card.getWidth() <= 500,
                "small workspace keeps the card reachable");
            mentor.setSize(2000, 1200);mentor.doLayout();
            check(card.getWidth() == 962, "workspace growth cannot bypass the cap");
            mentor.close();
        });
        System.out.println("FloatingMentorWidthTest passed");
    }
    private static void resize(FloatingMentor mentor, String name, int dx, int dy) {
        JComponent grip = (JComponent)get(mentor, name);
        for (int id : new int[]{MouseEvent.MOUSE_PRESSED,MouseEvent.MOUSE_DRAGGED,MouseEvent.MOUSE_RELEASED}) {
            int x=id==MouseEvent.MOUSE_PRESSED?5:5+dx, y=id==MouseEvent.MOUSE_PRESSED?5:5+dy;
            grip.dispatchEvent(new MouseEvent(grip,id,System.currentTimeMillis(),0,x,y,x,y,1,false,MouseEvent.BUTTON1));
        }
    }
    private static Object get(Object owner, String name) {
        try { Field f=owner.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(owner); }
        catch (ReflectiveOperationException e) { throw new RuntimeException(e); }
    }
    private static void check(boolean pass, String reason) { if(!pass)throw new AssertionError(reason); }
}
