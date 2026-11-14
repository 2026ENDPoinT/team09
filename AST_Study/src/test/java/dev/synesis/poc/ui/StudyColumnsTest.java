package dev.synesis.poc.ui;

import javax.swing.*;
import java.awt.*;
import java.lang.reflect.Field;

/** Real timers and retained Swing state, without an application window or worker. */
public final class StudyColumnsTest {
    private static StudyColumns columns;
    private static JPanel root;
    private static JTextArea a,b,c;
    private static JScrollPane av,bv,cv;
    private static JSplitPane split;
    private static int divider;
    public static void main(String[] args)throws Exception {
        edt(()->{
            root=new JPanel(new BorderLayout()){@Override public boolean isShowing(){return true;}};
            columns=new StudyColumns();root.add(columns);root.setSize(1100,700);root.addNotify();
            a=new JTextArea("A state\n".repeat(200));b=new JTextArea("B state\n".repeat(200));c=new JTextArea("C state\n".repeat(200));
            for(JTextArea text:new JTextArea[]{a,b,c})text.setCaret(new javax.swing.text.DefaultCaret(){
                @Override protected void adjustVisibility(Rectangle rectangle){} // Read-only study text does not chase the caret.
            });
            av=new JScrollPane(a);bv=new JScrollPane(b);cv=new JScrollPane(c);
            columns.register("A","A",av);columns.register("B","B",bv);columns.register("C","C",cv);
            layout(root);columns.open("A");layout(root);a.select(2,7);
            av.getViewport().setViewPosition(new Point(0,180));columns.open("B");
        });
        Thread.sleep(650);
        edt(()->{
            layout(root);split=(JSplitPane)get(columns,"split");split.setDividerLocation(420);layout(root);divider=split.getDividerLocation();
        });
        Thread.sleep(350);
        edt(()->{
            av.getViewport().setViewPosition(new Point(0,180));bv.getViewport().setViewPosition(new Point(0,240));
            columns.select(0,"B");
        });
        Thread.sleep(450);
        edt(()->{
            check(av.getParent()==split.getRightComponent()&&bv.getParent()==split.getLeftComponent(),"swap retained instances");
            check(divider==split.getDividerLocation(),"swap leaves physical divider unchanged");
            check(a.getSelectionStart()==2&&a.getSelectionEnd()==7,"text selection survives swap");
            check(av.getViewport().getViewPosition().y>=170&&bv.getViewport().getViewPosition().y>=230,"scroll travels with content: "+av.getViewport().getViewPosition()+" / "+bv.getViewport().getViewPosition());
            columns.select(0,"C");columns.select(0,"A");columns.select(1,"C");
        });
        Thread.sleep(450);
        edt(()->{
            check(av.getParent()==split.getLeftComponent()&&cv.getParent()==split.getRightComponent(),"rapid switches commit latest request atomically");
            check(!columns.addButton().isVisible(),"two slot capacity");
            check(get(columns,"exchange")==null&&get(columns,"transition")==null,"no idle controller timer");
            columns.closeView("A");
        });
        Thread.sleep(650);
        edt(()->{
            check(columns.count()==1&&split.getLeftComponent()==null&&cv.getParent()==split.getRightComponent(),"closing first expands survivor");
            columns.closeView("C");check(columns.count()==0&&columns.addButton().isVisible(),"all closed remains reopenable");
            columns.open("A");layout(root);check(columns.count()==1&&av.getParent()==split.getLeftComponent(),"reopen retained feature");
            columns.dispose();root.removeNotify();
        });
        System.out.println("PASS StudyColumns: swap, stable widths, scroll/selection, rapid input, close/reopen and idle timers");
    }
    static void edt(Runnable action)throws Exception{SwingUtilities.invokeAndWait(action);}
    static Object get(Object o,String key){try{Field f=o.getClass().getDeclaredField(key);f.setAccessible(true);return f.get(o);}catch(Exception e){throw new RuntimeException(e);}}
    static void layout(Container c){c.doLayout();for(Component child:c.getComponents())if(child.isVisible()&&child instanceof Container nested)layout(nested);}
    static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
}
