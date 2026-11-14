package dev.synesis.poc.ui;

import java.awt.*;
import java.awt.event.*;
import javax.swing.*;

/** Decorative frames belong to the visible, active window, not just a displayable component. */
public final class AnimationWindow {
    private AnimationWindow() {}
    public static boolean active(Component component) {
        if(!component.isShowing())return false;
        Window window=SwingUtilities.getWindowAncestor(component);
        return window==null || window.isActive()
            && (!(window instanceof Frame frame)||(frame.getExtendedState()&Frame.ICONIFIED)==0);
    }
    static void observe(JComponent component,Runnable changed) {
        watch(component,changed);
    }
    /** Returns an idempotent unsubscribe action for components with an explicit close lifecycle. */
    public static Runnable watch(JComponent component,Runnable changed) {
        class Observer extends WindowAdapter implements HierarchyListener {
            private Window window;
            private boolean closed;
            void sync() {
                if(closed)return;
                Window next=component.isDisplayable()?SwingUtilities.getWindowAncestor(component):null;
                if(window!=next) {
                    if(window!=null)window.removeWindowListener(this);
                    window=next;
                    if(window!=null)window.addWindowListener(this);
                }
                changed.run();
            }
            void dispose() {
                if(closed)return;closed=true;
                component.removeHierarchyListener(this);
                if(window!=null)window.removeWindowListener(this);
                window=null;
            }
            @Override public void hierarchyChanged(HierarchyEvent event) {
                if((event.getChangeFlags()&(HierarchyEvent.SHOWING_CHANGED|HierarchyEvent.DISPLAYABILITY_CHANGED|HierarchyEvent.PARENT_CHANGED))!=0)sync();
            }
            @Override public void windowActivated(WindowEvent event){changed.run();}
            @Override public void windowDeactivated(WindowEvent event){changed.run();}
            @Override public void windowIconified(WindowEvent event){changed.run();}
            @Override public void windowDeiconified(WindowEvent event){changed.run();}
            @Override public void windowClosed(WindowEvent event){sync();}
        }
        Observer observer=new Observer();component.addHierarchyListener(observer);observer.sync();
        return observer::dispose;
    }
}
