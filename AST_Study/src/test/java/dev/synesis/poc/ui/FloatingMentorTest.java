package dev.synesis.poc.ui;

import javax.swing.*;
import java.awt.*;
import java.awt.event.*;
import java.lang.reflect.Field;

/** No native windows: open/close lifecycle, input passthrough and bounded idle work. */
public final class FloatingMentorTest {
    private static JPanel root,chat;
    private static FloatingMentor mentor;
    private static JTextArea entry;
    private static JToggleButton navigation,studyTab;
    public static void main(String[] args)throws Exception{
        edt(()->{
            root=new JPanel(new BorderLayout()){@Override public boolean isShowing(){return true;}};
            mentor=new FloatingMentor();root.add(mentor);root.setSize(1100,800);root.addNotify();
            chat=new JPanel(new BorderLayout());entry=new JTextArea("보존할 입력");chat.add(entry);
            navigation=mentor.createNavigationToggle();
            StudyTabStrip tabs=new StudyTabStrip();studyTab=new StudyTabStrip.Tab("강의 해설");
            tabs.add(studyTab);studyTab.setSelected(true);
            JPanel header=new JPanel(new BorderLayout());header.add(tabs);header.add(navigation,BorderLayout.EAST);
            mentor.setContent(chat);layout(root);navigation.doClick(0);
        });
        Thread.sleep(500);
        edt(()->{
            check(mentor.isOpen()&&entry.getText().equals("보존할 입력"),"opens original chat");
            check(navigation.isSelected()&&studyTab.isSelected(),"navigation toggle is independent of the study selection");
            JComponent orb=(JComponent)get(mentor,"orb");
            Icon normal=MentorAvatar.icon(MentorAvatar.SIZE),hover=MentorAvatar.icon(MentorAvatar.HOVER_SIZE);
            check(Math.abs(normal.getIconWidth()-102*.8)<1,"resting artwork is not 80% of its prior size");
            check(hover.getIconWidth()/(double)normal.getIconWidth()>1.28,"hover does not enlarge artwork by about 30%");
            check(orb.getWidth()>=hover.getIconWidth()&&orb.getHeight()>=hover.getIconHeight(),"hover shadow clips against drag target");
            check(!((Timer)get(mentor,"motion")).isRunning()&&get(mentor,"snapshot")==null,"opening releases timer and snapshot");
            check(!mentor.contains(20,20),"outside overlay passes clicks and scroll through");
            ((JButton)orb).doClick(0);
            check(!mentor.isOpen()&&!navigation.isSelected(),"orb close synchronizes navigation");
            navigation.doClick(0);
            check(mentor.isOpen()&&navigation.isSelected(),"navigation reopens the same chat");
            navigation.doClick(0);
            check(!mentor.isOpen()&&!navigation.isSelected()&&studyTab.isSelected(),"second navigation click closes without changing study selection");
            mentor.setOpen(false);mentor.setOpen(true);mentor.setOpen(false);
        });
        Thread.sleep(500);
        edt(()->{
            check(!mentor.isOpen()&&!((JComponent)get(mentor,"card")).isVisible(),"rapid toggle ends closed");
            check(!((Timer)get(mentor,"motion")).isRunning()&&get(mentor,"snapshot")==null,"closed has no redraw loop or snapshot");
            mentor.setOpen(true,false);layout(root);
            JComponent grip=(JComponent)get(mentor,"southeast");
            Rectangle before=((JComponent)get(mentor,"card")).getBounds();
            Point orbBefore=((JComponent)get(mentor,"orb")).getLocation();
            mouse(grip,MouseEvent.MOUSE_PRESSED,5,5);mouse(grip,MouseEvent.MOUSE_DRAGGED,-75,-85);mouse(grip,MouseEvent.MOUSE_RELEASED,-75,-85);
            Rectangle after=((JComponent)get(mentor,"card")).getBounds();
            check(after.width<before.width&&after.height<before.height,"resize changes shell size");
            Point orbAfter=((JComponent)get(mentor,"orb")).getLocation();
            check(orbAfter.x-orbBefore.x==after.x+after.width-before.x-before.width&&orbAfter.y-orbBefore.y==after.y+after.height-before.y-before.height,"orb follows resized bottom-right corner");
            check(!((Timer)get(mentor,"motion")).isRunning(),"resize release leaves no idle timer");
            check(entry.getText().equals("보존할 입력")&&entry.getParent()==chat,"resize keeps composer instance and text");
            root.setSize(480,500);layout(root);Rectangle small=((JComponent)get(mentor,"card")).getBounds();
            check(small.x>=0&&small.y>=0&&small.getMaxX()<=mentor.getWidth()&&small.getMaxY()<=mentor.getHeight(),"window shrink keeps controls reachable");
            mentor.setOpen(false,false);root.setSize(1400,1000);layout(root);
            try{
                Field anchor=FloatingMentor.class.getDeclaredField("orbPosition");anchor.setAccessible(true);
                JComponent orb=(JComponent)get(mentor,"orb");int half=orb.getWidth()/2;
                for(Point center:new Point[]{new Point(41,900),new Point(250,900),new Point(1150,900),new Point(1359,900),new Point(250,80)}){
                    anchor.set(mentor,new Point(center.x-half,center.y-half));
                    Field manual=FloatingMentor.class.getDeclaredField("cardPosition");manual.setAccessible(true);manual.set(mentor,null);
                    mentor.setOpen(true,false);mentor.doLayout();Rectangle actual=((JComponent)get(mentor,"card")).getBounds();
                    Point expected=FloatingChatPlacement.place(1400,1000,actual.width,actual.height,new Point(orb.getX()+half,orb.getY()+half),null,MentorAvatar.SIZE);
                    check(actual.getLocation().equals(expected),"placement accounts for mentor size at "+center);
                    mentor.setOpen(false,false);
                }
                check(FloatingChatPlacement.place(1400,1000,460,700,new Point(250,900),null).x==294,"free left orb opens chat on right");
                check(FloatingChatPlacement.place(1400,1000,460,700,new Point(1150,900),null).x==646,"free right orb opens chat on left");
                check(FloatingChatPlacement.place(1400,1000,460,700,new Point(34,900),null).x==10,"docked left orb aligns inset corner");
                check(FloatingChatPlacement.place(1400,1000,460,700,new Point(1366,900),null).x==930,"docked right orb aligns inset corner");
                check(FloatingChatPlacement.place(1400,1000,460,700,new Point(250,80),null).y==120,"top orb opens chat below");
                check(FloatingChatPlacement.place(1400,1000,460,700,new Point(250,80),null,MentorAvatar.SIZE).y==128,"top orb leaves room below the icon");
                check(FloatingChatPlacement.place(1400,1000,460,700,new Point(41,900),null,MentorAvatar.SIZE).x==12,"docked orb aligns its visible edge");
            }catch(ReflectiveOperationException e){throw new RuntimeException(e);}
            mentor.close();root.removeNotify();
        });
        System.out.println("PASS FloatingMentor: synchronized navigation, original content, 80% resting icon, stronger hover, rapid transitions, idle, passthrough, resize and viewport clamp");
    }
    static void mouse(JComponent c,int id,int x,int y){c.dispatchEvent(new MouseEvent(c,id,System.currentTimeMillis(),0,x,y,x,y,1,false,MouseEvent.BUTTON1));}
    static void edt(Runnable action)throws Exception{SwingUtilities.invokeAndWait(action);}
    static Object get(Object o,String key){try{Field f=o.getClass().getDeclaredField(key);f.setAccessible(true);return f.get(o);}catch(Exception e){throw new RuntimeException(e);}}
    static void layout(Container c){c.doLayout();for(Component child:c.getComponents())if(child.isVisible()&&child instanceof Container nested)layout(nested);}
    static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
}
