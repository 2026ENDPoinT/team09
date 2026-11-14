package dev.synesis.poc.ui;

import dev.synesis.poc.planner.*;
import javax.swing.*;
import javax.imageio.ImageIO;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.nio.file.*;
import java.time.*;
import java.util.List;
import java.util.ArrayList;
import static dev.synesis.poc.planner.PlannerModel.*;

/** Deadline restrictions, month/year boundaries, manual-entry bypass and optional-deadline persistence. */
public final class PlannerTodoDeadlineTest {
    static int checks;
    static void check(boolean value,String message){checks++;if(!value)throw new AssertionError(message);}
    static List<JComponent> named(Container root,String name){List<JComponent> out=new ArrayList<>();for(Component c:root.getComponents()){if(c instanceof JComponent j&&name.equals(j.getName()))out.add(j);if(c instanceof Container next)out.addAll(named(next,name));}return out;}
    static List<JButton> days(Container root){List<JButton> out=new ArrayList<>();for(Component c:root.getComponents()){if(c instanceof JButton b&&b.getClientProperty("planner.date")!=null)out.add(b);if(c instanceof Container next)out.addAll(days(next));}return out;}
    public static void main(String[] args)throws Exception {
        Path output=Path.of("tmp/weekly-v-20261018/deadline");Files.createDirectories(output);PlannerStore store=new PlannerStore(Files.createTempDirectory("synesis-todo-deadline-").resolve("planner.json"));
        SwingUtilities.invokeAndWait(()->{try{
            PlannerDesign p=new PlannerDesign(store,Clock.fixed(Instant.parse("2026-10-18T04:00:00Z"),ZoneId.of("Asia/Seoul")));PlannerWeekEditors.Todo editor=new PlannerWeekEditors.Todo(p,null);
            JPopupMenu popup=editor.deadline.popup();List<JButton> days=days(popup);
            check(days.stream().filter(AbstractButton::isEnabled).count()==7,"only seven dates enabled");
            for(JButton button:days){LocalDate date=(LocalDate)button.getClientProperty("planner.date");boolean inWeek=weekStart(date).equals(LocalDate.of(2026,10,12));check(button.isEnabled()==inWeek,"restricted date "+date);if(!inWeek)check(button.getBackground().equals(new Color(0xf2f2f2)),"out-of-week date is gray "+date);}
            LocalDate before=editor.deadline.date();JTextField direct=(JTextField)named(popup,"날짜 직접 입력").get(0);JButton apply=(JButton)named(popup,"적용").get(0);direct.setText("2026-10-19");apply.doClick();check(editor.deadline.date().equals(before),"manual input cannot bypass week restriction");
            direct.setText("2026-10-15");apply.doClick();check(editor.deadline.date().equals(LocalDate.of(2026,10,15)),"manual input accepts date inside week");
            editor.week.setDate(LocalDate.of(2026,12,31));check(weekStart(editor.deadline.date()).equals(LocalDate.of(2026,12,28)),"changing TODO week moves deadline inside selected week");
            popup=editor.deadline.popup();check(days(popup).stream().filter(AbstractButton::isEnabled).count()==7,"cross-year week includes seven dates across months");
            JButton next=(JButton)named(popup,"다음 달").get(0);check(next.isEnabled(),"cross-month week allows next month");next.doClick();check(days(popup).stream().filter(AbstractButton::isEnabled).count()==7,"next month keeps the same seven allowed dates");check(!next.isEnabled(),"cannot navigate beyond week months");
            editor.noDeadline.doClick();check(!editor.deadline.isEnabled(),"no-deadline option disables explicit date");editor.title.setText("이번 주 안에 공부하기");editor.save();WeeklyTask saved=store.load().weeklyTasks().get(0);check(saved.deadline()==null&&saved.week().equals(LocalDate.of(2026,12,28)),"no explicit deadline persists with assigned week");
            PlannerWeekEditors.Todo restored=new PlannerWeekEditors.Todo(p,saved);check(restored.noDeadline.isSelected()&&!restored.deadline.isEnabled(),"no-deadline option restored when editing");restored.noDeadline.doClick();check(restored.deadline.isEnabled(),"can return to a specific deadline");restored.deadline.setDate(LocalDate.of(2027,1,2));restored.save();check(store.load().weeklyTasks().get(0).deadline().equals(LocalDate.of(2027,1,2)),"specific deadline saves after no-deadline mode");
            PlannerWeekEditors.Todo sample=new PlannerWeekEditors.Todo(p,null);sample.title.setText("와우~ 이번주엔 공부좀 하자.");sample.setSize(480,560);PlannerWeeklyVTest.layout(sample);BufferedImage image=new BufferedImage(480,560,BufferedImage.TYPE_INT_RGB);Graphics2D g=image.createGraphics();sample.printAll(g);g.dispose();ImageIO.write(image,"png",output.resolve("editor.png").toFile());
            popup=sample.deadline.popup();popup.setSize(popup.getPreferredSize());PlannerWeeklyVTest.layout(popup);image=new BufferedImage(popup.getWidth(),popup.getHeight(),BufferedImage.TYPE_INT_RGB);g=image.createGraphics();popup.printAll(g);g.dispose();ImageIO.write(image,"png",output.resolve("week-only-calendar.png").toFile());
            PlannerDialogs.DateInput normal=new PlannerDialogs.DateInput("일정 날짜",LocalDate.of(2026,10,18));check(days(normal.popup()).stream().allMatch(AbstractButton::isEnabled),"ordinary event/day date pickers remain unrestricted");
        }catch(Exception e){throw new RuntimeException(e);}});
        System.out.println("PASS: "+checks+" TODO deadline checks");
    }
}
