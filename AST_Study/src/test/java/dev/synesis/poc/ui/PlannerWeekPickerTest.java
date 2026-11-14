package dev.synesis.poc.ui;

import javax.swing.*;
import javax.imageio.ImageIO;
import java.awt.*;
import java.awt.event.MouseEvent;
import java.nio.file.*;
import java.time.*;
import java.util.List;
import static dev.synesis.poc.planner.PlannerModel.*;
import static dev.synesis.poc.ui.PlannerStyle.*;

/** Whole-week hover/selection, month boundaries, and isolation from ordinary date pickers. */
public final class PlannerWeekPickerTest {
    static int checks;
    static void check(boolean value,String message){checks++;if(!value)throw new AssertionError(message);}
    static List<JButton> days(Container popup){return PlannerTodoDeadlineTest.days(popup);}
    static JButton day(Container popup,LocalDate value){return days(popup).stream().filter(b->value.equals(b.getClientProperty("planner.date"))).findFirst().orElseThrow();}
    public static void main(String[] args)throws Exception{
        Path out=Path.of("tmp/week-picker-20261019");Files.createDirectories(out);
        SwingUtilities.invokeAndWait(()->{try{
            var input=PlannerWeekEditors.weekInput("TODO의 주",LocalDate.of(2026,10,28));
            JPopupMenu pop=input.popup();List<JButton> days=days(pop);
            check(input.date().equals(LocalDate.of(2026,10,26)),"week value normalized to Monday");
            check(((LocalDate)days.get(0).getClientProperty("planner.date")).getDayOfWeek()==DayOfWeek.MONDAY,"week selector presents Monday–Sunday rows");
            check(days.stream().filter(b->NAVY.equals(b.getBackground())).count()==7,"all seven selected dates are navy");
            check(day(pop,LocalDate.of(2026,11,1)).getForeground().equals(Color.WHITE),"selected Sunday remains white across month boundary");
            JButton hovered=day(pop,LocalDate.of(2026,10,21));hovered.dispatchEvent(new MouseEvent(hovered,MouseEvent.MOUSE_ENTERED,0,0,10,10,0,false));
            for(JButton b:days){LocalDate date=(LocalDate)b.getClientProperty("planner.date");if(weekStart(date).equals(LocalDate.of(2026,10,19)))check(b.getBackground().equals(new Color(0xdce9fa)),"hover highlights whole week: "+date);}
            check(days.stream().filter(b->NAVY.equals(b.getBackground())).count()==7,"hover preserves existing selected week");
            pop.setSize(pop.getPreferredSize());PlannerWeekOverviewTest.layout(pop);ImageIO.write(PlannerWeekOverviewTest.paint(pop),"png",out.resolve("selected-and-hovered-weeks.png").toFile());
            hovered.dispatchEvent(new MouseEvent(hovered,MouseEvent.MOUSE_EXITED,0,0,-1,-1,0,false));
            check(days.stream().noneMatch(b->b.getBackground().equals(new Color(0xdce9fa))),"hover clears when pointer leaves");
            day(pop,LocalDate.of(2026,10,25)).doClick(0);check(input.date().equals(LocalDate.of(2026,10,19)),"Sunday click selects its Monday–Sunday week");
            check(input.getText().equals("2026.10.19 — 10.25"),"field displays selected week range");
            pop=input.popup();check(days(pop).stream().filter(b->NAVY.equals(b.getBackground())).count()==7,"selection restored across popup reopening");
            JTextField direct=(JTextField)PlannerTodoDeadlineTest.named(pop,"날짜 직접 입력").get(0);direct.setText("2026-12-31");((JButton)PlannerTodoDeadlineTest.named(pop,"적용").get(0)).doClick(0);
            check(input.date().equals(LocalDate.of(2026,12,28)),"direct date input selects entire cross-year week");
            pop=input.popup();check(days(pop).stream().filter(b->NAVY.equals(b.getBackground())).count()==7,"cross-year selection highlights seven dates");
            var ordinary=new PlannerDialogs.DateInput("일정 날짜",LocalDate.of(2026,10,28));pop=ordinary.popup();
            check(days(pop).stream().filter(b->NAVY.equals(b.getBackground())).count()==1,"ordinary picker retains single-date selection");
            check(((LocalDate)days(pop).get(0).getClientProperty("planner.date")).getDayOfWeek()==DayOfWeek.SUNDAY,"ordinary picker retains Sunday-first layout");
        }catch(Exception e){throw new RuntimeException(e);}});
        System.out.println("PASS: "+checks+" week picker checks");
    }
}
