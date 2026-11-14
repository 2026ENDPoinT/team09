package dev.synesis.poc.ui;

import dev.synesis.poc.planner.*;
import javax.imageio.ImageIO;
import javax.swing.*;
import java.awt.*;
import java.awt.event.MouseEvent;
import java.awt.image.BufferedImage;
import java.nio.file.*;
import java.time.*;
import java.util.*;
import java.util.List;
import java.util.concurrent.atomic.*;
import static dev.synesis.poc.planner.PlannerModel.*;

/** All dismissal paths require confirmation; successful writes bypass discard confirmation. */
public final class PlannerDismissalTest {
    private static int checks;
    private static void check(boolean value,String message){checks++;if(!value)throw new AssertionError(message);}
    public static void main(String[] args)throws Exception {
        Path root=Files.createTempDirectory("synesis-planner-dismissal-");PlannerStore store=new PlannerStore(root.resolve("planner.json"));
        Clock clock=Clock.fixed(Instant.parse("2026-10-18T03:00:00Z"),ZoneId.of("Asia/Seoul"));
        SwingUtilities.invokeAndWait(()->{try{
            State state=store.saveTags(List.of(),List.of(new Tag("exam","시험")));
            PlannerDialogs.EventEditor editor=new PlannerDialogs.EventEditor(store,state,null,LocalDateTime.of(2026,10,18,10,0),s->{},clock);
            editor.title.setText("보존할 일정");editor.description.setText("작성 중인 설명");editor.selected.add("exam");editor.endTime.setSelectedItem("12:30");editor.renderTags();
            AtomicInteger closes=new AtomicInteger(),prompts=new AtomicInteger();AtomicReference<JPanel> shown=new AtomicReference<>();
            editor.putClientProperty("planner.close",(Runnable)closes::incrementAndGet);editor.discardPresenter=panel->{prompts.incrementAndGet();shown.set(panel);};
            PlannerModel.Event before=editor.draft();
            findButton(editor,"취소").doClick();check(prompts.get()==1&&closes.get()==0,"cancel prompts before closing");
            JPanel prompt=shown.get();check(prompt.getClientProperty("planner.defaultButton")==findButton(prompt,"계속 작성"),"Enter defaults to keeping the draft");
            render(prompt);findButton(editor,"×").doClick();check(prompts.get()==1,"repeated requests cannot stack confirmation prompts");
            findButton(prompt,"계속 작성").doClick();check(closes.get()==0&&editor.discardPrompt==null,"continue writing dismisses only the confirmation");
            check(sameContent(before,editor.draft()),"continue writing preserves every draft field");
            findButton(editor,"×").doClick();check(prompts.get()==2&&closes.get()==0,"X uses the same confirmation");
            PlannerDialogs.requestClose(shown.get());check(editor.discardPrompt==null&&closes.get()==0,"Escape or OS close on confirmation keeps the draft");
            PlannerDialogs.DialogBackdrop backdrop=new PlannerDialogs.DialogBackdrop(editor,920,804,()->PlannerDialogs.requestClose(editor));
            backdrop.setSize(1126,800);layout(backdrop);check(editor.getX()>0&&editor.getY()>0&&editor.getX()+editor.getWidth()<backdrop.getWidth()&&editor.getY()+editor.getHeight()<backdrop.getHeight(),"editor and clickable dim area fit the owner");
            click(backdrop);check(prompts.get()==3&&closes.get()==0,"backdrop click requires confirmation");
            findButton(shown.get(),"계속 작성").doClick();check(sameContent(before,editor.draft()),"backdrop cancellation preserves the draft");
            int count=prompts.get();click(editor);check(prompts.get()==count,"clicking inside the form never dismisses it");
            PlannerDialogs.requestClose(editor);check(prompts.get()==4,"Escape or OS close on the editor requires confirmation");
            findButton(shown.get(),"닫기").doClick();check(closes.get()==1&&store.load().events().isEmpty(),"confirmed dismissal closes without saving the draft");
            PlannerDialogs.EventEditor save=new PlannerDialogs.EventEditor(store,state,null,before.start(),s->{},clock);save.title.setText("정상 저장");save.putClientProperty("planner.close",(Runnable)closes::incrementAndGet);save.discardPresenter=p->{throw new AssertionError("save requested discard confirmation");};save.save();
            check(closes.get()==2&&store.load().events().size()==1,"successful save closes directly without discard confirmation");
            PlannerDialogs.EventEditor invalid=new PlannerDialogs.EventEditor(store,store.load(),null,before.start(),s->{},clock);invalid.title.setText("미완성");invalid.startTime.getEditor().setItem("잘못된 시간");invalid.discardPresenter=shown::set;
            PlannerDialogs.requestClose(invalid);check(invalid.discardPrompt!=null,"incomplete or invalid drafts can still be cancelled");
            findButton(shown.get(),"계속 작성").doClick();check(invalid.startTime.getEditor().getItem().equals("잘못된 시간"),"continuing preserves even incomplete input");
            State beforeList=store.load();PlannerDesign planner=new PlannerDesign(store,clock);planner.accept(beforeList);JPanel day=planner.dayEventsPanel(before.start().toLocalDate());
            AtomicInteger listCloses=new AtomicInteger();day.putClientProperty("planner.close",(Runnable)listCloses::incrementAndGet);
            check(Boolean.TRUE.equals(day.getClientProperty("planner.backdropDismiss")),"day list uses the clickable modal backdrop");
            findButton(day,"닫기").doClick();check(listCloses.get()==1,"day list close button closes directly without discard confirmation");
            PlannerDialogs.DialogBackdrop dayBackdrop=new PlannerDialogs.DialogBackdrop(day,480,420,()->PlannerDialogs.requestClose(day));dayBackdrop.setSize(1126,800);layout(dayBackdrop);
            click(dayBackdrop);check(listCloses.get()==2,"day list background click closes directly");click(day);check(listCloses.get()==2,"clicking within the day list leaves it open");
            PlannerDialogs.requestClose(day);check(listCloses.get()==3,"day list Escape and window close share the direct close action");
            check(store.load().equals(beforeList),"closing the day list never changes saved planner data");
            testInlineDay(day);
            testInlineEditor(store,clock);
            testUnchangedDismissal(store,clock);
        }catch(Exception error){throw new RuntimeException(error);}});
        System.out.println("PASS: "+checks+" planner dismissal, draft preservation and save checks");
    }
    private static void testInlineDay(JPanel day)throws Exception {
        JRootPane root=new JRootPane();JPanel background=new JPanel(new BorderLayout()){
            @Override protected void paintComponent(Graphics g){super.paintComponent(g);for(int x=0;x<getWidth();x+=40){g.setColor((x/40)%2==0?new Color(0x24405a):new Color(0xd4dde8));g.fillRect(x,0,40,getHeight());}}
        };
        JButton previous=new JButton("배경 버튼");background.add(previous,BorderLayout.SOUTH);root.setContentPane(background);root.setDefaultButton(previous);root.setSize(1126,800);layout(root);
        Rectangle rootBounds=root.getBounds();int windows=Window.getWindows().length,children=root.getLayeredPane().getComponentCount();
        PlannerDayOverlay overlay=new PlannerDayOverlay(root,day,480,420);overlay.showOverlay();overlay.animation.stop();
        check(Window.getWindows().length==windows,"day list does not create a native window that could zoom the app background");
        check(root.getBounds().equals(rootBounds),"opening the day list never resizes the main window");
        BufferedImage[] frames=new BufferedImage[3];float[] progress={0,.5f,1};Path output=Path.of("build/planner-dismissal-20261018");Files.createDirectories(output);
        for(int i=0;i<frames.length;i++){overlay.progress=progress[i];frames[i]=paint(root);ImageIO.write(frames[i],"png",output.resolve("day-open-"+i+".png").toFile());}
        Rectangle small=day.getBounds();boolean stable=true;
        for(int i=1;i<frames.length;i++){
            double scale=.96+.04*progress[i];int left=(int)Math.round(small.getCenterX()-small.width*scale/2),top=(int)Math.round(small.getCenterY()-small.height*scale/2);
            int right=(int)Math.round(small.getCenterX()+small.width*scale/2)-1,bottom=(int)Math.round(small.getCenterY()+small.height*scale/2)-1;
            for(Point corner:List.of(new Point(left+1,top+1),new Point(right-1,top+1),new Point(left+1,bottom-1),new Point(right-1,bottom-1)))
                check(frames[i].getRGB(corner.x,corner.y)==frames[0].getRGB(corner.x,corner.y),"popup corners stay transparent during opening and after animation");
        }
        for(int y=0;y<root.getHeight()&&stable;y++)for(int x=0;x<root.getWidth();x++)if(!small.contains(x,y)&&(frames[0].getRGB(x,y)!=frames[1].getRGB(x,y)||frames[0].getRGB(x,y)!=frames[2].getRGB(x,y))){stable=false;break;}
        check(stable,"every background pixel stays fixed throughout the popup animation");
        int cx=(int)small.getCenterX(),cy=(int)small.getCenterY();check(frames[0].getRGB(cx,cy)!=frames[2].getRGB(cx,cy),"only the small day-list panel fades and grows into view");
        click(day);check(overlay.getParent()!=null,"clicking the day-list contents does not close its overlay");
        click(overlay);check(overlay.getParent()==null&&root.getLayeredPane().getComponentCount()==children,"outside click removes the day overlay completely");
        check(root.getDefaultButton()==previous&&!overlay.animation.isRunning(),"closing restores the prior default action and stops animation");
        PlannerDayOverlay second=new PlannerDayOverlay(root,day,480,420);second.showOverlay();findButton(day,"닫기").doClick();check(second.getParent()==null,"close button also removes the in-window day list");
    }
    private static void testInlineEditor(PlannerStore store,Clock clock)throws Exception {
        JRootPane root=new JRootPane();JPanel background=new JPanel();background.setBackground(new Color(0x426080));root.setContentPane(background);root.setSize(1200,900);layout(root);
        PlannerDialogs.EventEditor editor=new PlannerDialogs.EventEditor(store,store.load(),null,LocalDateTime.of(2026,10,18,10,0),s->{},clock);editor.title.setText("애니메이션 중 보존");
        int windows=Window.getWindows().length;Rectangle bounds=root.getBounds();PlannerDialogs.showDialog(background,editor,"일정 추가",920,804);
        PlannerDayOverlay overlay=Arrays.stream(root.getLayeredPane().getComponents()).filter(c->c instanceof PlannerDayOverlay).map(c->(PlannerDayOverlay)c).findFirst().orElseThrow();overlay.animation.stop();
        check(Window.getWindows().length==windows&&root.getBounds().equals(bounds),"event editor opens without any new native window or main-window resize");
        BufferedImage[] frames=new BufferedImage[3];float[] stages={0,.5f,1};Path out=Path.of("build/planner-dismissal-20261018");
        for(int i=0;i<stages.length;i++){overlay.progress=stages[i];frames[i]=paint(root);ImageIO.write(frames[i],"png",out.resolve("editor-open-"+i+".png").toFile());}
        boolean stable=true;for(int y=0;y<root.getHeight()&&stable;y++)for(int x=0;x<root.getWidth();x++)if(!editor.getBounds().contains(x,y)&&(frames[0].getRGB(x,y)!=frames[1].getRGB(x,y)||frames[0].getRGB(x,y)!=frames[2].getRGB(x,y))){stable=false;break;}
        check(stable,"editor animation keeps every background pixel fixed");check(editor.title.getText().equals("애니메이션 중 보존"),"opening preserves the editor draft");
        editor.showTagPopup();check(editor.tagPopover!=null,"tag picker still opens above the in-window editor");
        java.awt.event.KeyEvent escape=new java.awt.event.KeyEvent(editor.addTag,java.awt.event.KeyEvent.KEY_PRESSED,0,0,java.awt.event.KeyEvent.VK_ESCAPE,(char)27);
        check(!overlay.key(escape),"editor lets the tag picker handle Escape before draft dismissal");editor.hideTagPopup();
        JPopupMenu menu=new JPopupMenu();JMenuItem item=new JMenuItem("날짜");menu.add(item);MenuSelectionManager.defaultManager().setSelectedPath(new MenuElement[]{menu,item});
        check(!overlay.key(escape),"date and time menus retain their keyboard handling");MenuSelectionManager.defaultManager().clearSelectedPath();
        AtomicReference<JPanel> prompt=new AtomicReference<>();editor.discardPresenter=prompt::set;click(overlay);check(prompt.get()!=null&&overlay.getParent()!=null,"editor backdrop still asks before discarding");
        findButton(prompt.get(),"계속 작성").doClick();check(editor.title.getText().equals("애니메이션 중 보존"),"declining discard keeps editor contents");
        check(overlay.key(escape),"Escape requests editor dismissal once child popups close");findButton(prompt.get(),"닫기").doClick();check(overlay.getParent()==null&&!overlay.animation.isRunning(),"confirmed editor dismissal cleans up the overlay and timer");
    }
    private static void testUnchangedDismissal(PlannerStore store,Clock clock)throws Exception {
        State before=store.load();LocalDateTime seed=LocalDateTime.of(2026,10,18,10,0);AtomicInteger closes=new AtomicInteger();
        PlannerDialogs.EventEditor blank=new PlannerDialogs.EventEditor(store,before,null,seed,s->{},clock);
        blank.putClientProperty("planner.close",(Runnable)closes::incrementAndGet);blank.discardPresenter=p->{throw new AssertionError("untouched blank editor must not prompt");};
        findButton(blank,"취소").doClick();findButton(blank,"×").doClick();PlannerDialogs.requestClose(blank);check(closes.get()==3,"all unchanged close paths bypass the warning");
        blank.title.setText("  ");blank.description.setText("\n  ");PlannerDialogs.requestClose(blank);check(closes.get()==4,"whitespace-only new text does not require a discard warning");
        PlannerModel.Event original=before.events().get(0);PlannerDialogs.EventEditor edit=new PlannerDialogs.EventEditor(store,before,original,original.start(),s->{},clock);
        edit.putClientProperty("planner.close",(Runnable)closes::incrementAndGet);edit.discardPresenter=p->{throw new AssertionError("unchanged existing event must not prompt");};PlannerDialogs.requestClose(edit);check(closes.get()==5,"unchanged existing event closes directly");
        edit.title.setText("수정했다가 취소");edit.title.setText(original.title());edit.description.setText("임시 설명");edit.description.setText(original.description());
        edit.important.setSelected(!original.important());edit.important.setSelected(original.important());edit.color=EventColor.ROSE;edit.color=original.color();edit.selected.add("temporary");edit.selected.remove("temporary");
        edit.startTime.getEditor().setItem("잘못된 시간");edit.startTime.getEditor().setItem(original.start().toLocalTime().toString());PlannerDialogs.requestClose(edit);check(closes.get()==6,"restoring edited fields to their original values clears the warning");
        PlannerDialogs.EventEditor options=new PlannerDialogs.EventEditor(store,before,null,seed,s->{},clock);AtomicInteger prompts=new AtomicInteger();options.discardPresenter=p->prompts.incrementAndGet();options.putClientProperty("planner.close",(Runnable)closes::incrementAndGet);
        options.color=EventColor.ROSE;PlannerDialogs.requestClose(options);check(prompts.get()==1&&closes.get()==6,"changing a non-text field still warns even with an empty title");
        options.finishDiscard(false);options.color=EventColor.NAVY;PlannerDialogs.requestClose(options);check(closes.get()==7,"reverting the non-text field returns to clean dismissal");
        options.startTime.getEditor().setItem("미완성 시간");PlannerDialogs.requestClose(options);check(prompts.get()==2,"dirty comparison preserves invalid unfinished time input without parsing");options.finishDiscard(false);
        check(store.load().equals(before),"clean and cancelled dismissal never writes planner data");
    }
    private static BufferedImage paint(JComponent component){BufferedImage image=new BufferedImage(component.getWidth(),component.getHeight(),BufferedImage.TYPE_INT_ARGB);Graphics2D g=image.createGraphics();component.printAll(g);g.dispose();return image;}
    private static boolean sameContent(PlannerModel.Event a,PlannerModel.Event b){return a.title().equals(b.title())&&a.description().equals(b.description())&&a.start().equals(b.start())&&a.end().equals(b.end())&&a.tagIds().equals(b.tagIds())&&a.color()==b.color()&&a.allDay()==b.allDay()&&a.important()==b.important()&&a.repeat()==b.repeat();}
    private static JButton findButton(Container root,String text){for(Component c:root.getComponents()){if(c instanceof JButton b&&text.equals(b.getText()))return b;if(c instanceof Container child){JButton result=findButton(child,text);if(result!=null)return result;}}return null;}
    private static void click(Component target){target.dispatchEvent(new MouseEvent(target,MouseEvent.MOUSE_PRESSED,System.currentTimeMillis(),0,2,2,1,false,MouseEvent.BUTTON1));}
    private static void layout(Container c){c.doLayout();for(Component child:c.getComponents())if(child instanceof Container nested)layout(nested);}
    private static void render(JPanel panel)throws Exception{panel.setSize(440,192);layout(panel);BufferedImage image=new BufferedImage(440,192,BufferedImage.TYPE_INT_ARGB);Graphics2D g=image.createGraphics();panel.printAll(g);g.dispose();Path output=Path.of("build/planner-dismissal-20261018");Files.createDirectories(output);ImageIO.write(image,"png",output.resolve("confirmation.png").toFile());}
}
