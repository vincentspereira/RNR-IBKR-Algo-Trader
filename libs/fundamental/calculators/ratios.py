"""Financial ratio calculators for fundamental analysis."""
from typing import Dict, Optional
from decimal import Decimal


class LiquidityRatios:
    """Calculate liquidity ratios."""
    
    @staticmethod
    def current_ratio(current_assets: Decimal, current_liabilities: Decimal) -> Optional[Decimal]:
        """Current Ratio = Current Assets / Current Liabilities"""
        if current_liabilities == 0:
            return None
        return current_assets / current_liabilities
    
    @staticmethod
    def quick_ratio(
        current_assets: Decimal,
        inventory: Decimal,
        current_liabilities: Decimal
    ) -> Optional[Decimal]:
        """Quick Ratio = (Current Assets - Inventory) / Current Liabilities"""
        if current_liabilities == 0:
            return None
        return (current_assets - inventory) / current_liabilities
    
    @staticmethod
    def cash_ratio(cash: Decimal, current_liabilities: Decimal) -> Optional[Decimal]:
        """Cash Ratio = Cash / Current Liabilities"""
        if current_liabilities == 0:
            return None
        return cash / current_liabilities


class ProfitabilityRatios:
    """Calculate profitability ratios."""
    
    @staticmethod
    def gross_margin(gross_profit: Decimal, revenue: Decimal) -> Optional[Decimal]:
        """Gross Margin = Gross Profit / Revenue"""
        if revenue == 0:
            return None
        return gross_profit / revenue
    
    @staticmethod
    def operating_margin(operating_income: Decimal, revenue: Decimal) -> Optional[Decimal]:
        """Operating Margin = Operating Income / Revenue"""
        if revenue == 0:
            return None
        return operating_income / revenue
    
    @staticmethod
    def net_margin(net_income: Decimal, revenue: Decimal) -> Optional[Decimal]:
        """Net Margin = Net Income / Revenue"""
        if revenue == 0:
            return None
        return net_income / revenue
    
    @staticmethod
    def roe(net_income: Decimal, shareholders_equity: Decimal) -> Optional[Decimal]:
        """ROE = Net Income / Shareholders' Equity"""
        if shareholders_equity == 0:
            return None
        return net_income / shareholders_equity
    
    @staticmethod
    def roa(net_income: Decimal, total_assets: Decimal) -> Optional[Decimal]:
        """ROA = Net Income / Total Assets"""
        if total_assets == 0:
            return None
        return net_income / total_assets
    
    @staticmethod
    def roic(
        nopat: Decimal,
        invested_capital: Decimal
    ) -> Optional[Decimal]:
        """ROIC = NOPAT / Invested Capital"""
        if invested_capital == 0:
            return None
        return nopat / invested_capital


class LeverageRatios:
    """Calculate leverage ratios."""
    
    @staticmethod
    def debt_to_equity(total_debt: Decimal, shareholders_equity: Decimal) -> Optional[Decimal]:
        """Debt-to-Equity = Total Debt / Shareholders' Equity"""
        if shareholders_equity == 0:
            return None
        return total_debt / shareholders_equity
    
    @staticmethod
    def debt_to_assets(total_debt: Decimal, total_assets: Decimal) -> Optional[Decimal]:
        """Debt-to-Assets = Total Debt / Total Assets"""
        if total_assets == 0:
            return None
        return total_debt / total_assets
    
    @staticmethod
    def interest_coverage(ebit: Decimal, interest_expense: Decimal) -> Optional[Decimal]:
        """Interest Coverage = EBIT / Interest Expense"""
        if interest_expense == 0:
            return None
        return ebit / interest_expense


class ValuationRatios:
    """Calculate valuation ratios."""
    
    @staticmethod
    def pe_ratio(price: Decimal, eps: Decimal) -> Optional[Decimal]:
        """P/E Ratio = Price / EPS"""
        if eps == 0:
            return None
        return price / eps
    
    @staticmethod
    def pb_ratio(price: Decimal, book_value_per_share: Decimal) -> Optional[Decimal]:
        """P/B Ratio = Price / Book Value per Share"""
        if book_value_per_share == 0:
            return None
        return price / book_value_per_share
    
    @staticmethod
    def ps_ratio(market_cap: Decimal, revenue: Decimal) -> Optional[Decimal]:
        """P/S Ratio = Market Cap / Revenue"""
        if revenue == 0:
            return None
        return market_cap / revenue
    
    @staticmethod
    def peg_ratio(pe_ratio: Decimal, earnings_growth_rate: Decimal) -> Optional[Decimal]:
        """PEG Ratio = P/E Ratio / Earnings Growth Rate"""
        if earnings_growth_rate == 0:
            return None
        return pe_ratio / earnings_growth_rate


class RatioCalculator:
    """Main ratio calculator combining all ratio types."""
    
    def __init__(self):
        self.liquidity = LiquidityRatios()
        self.profitability = ProfitabilityRatios()
        self.leverage = LeverageRatios()
        self.valuation = ValuationRatios()
    
    def calculate_all_ratios(self, financial_data: Dict) -> Dict:
        """
        Calculate all ratios from financial data.
        
        Args:
            financial_data: Dictionary containing financial statement data
            
        Returns:
            Dictionary of calculated ratios
        """
        ratios = {}
        
        # Extract data
        data = {k: Decimal(str(v)) if v is not None else Decimal(0) 
                for k, v in financial_data.items()}
        
        # Liquidity ratios
        ratios['current_ratio'] = self.liquidity.current_ratio(
            data.get('current_assets', Decimal(0)),
            data.get('current_liabilities', Decimal(0))
        )
        
        # Profitability ratios
        ratios['gross_margin'] = self.profitability.gross_margin(
            data.get('gross_profit', Decimal(0)),
            data.get('revenue', Decimal(0))
        )
        ratios['net_margin'] = self.profitability.net_margin(
            data.get('net_income', Decimal(0)),
            data.get('revenue', Decimal(0))
        )
        ratios['roe'] = self.profitability.roe(
            data.get('net_income', Decimal(0)),
            data.get('shareholders_equity', Decimal(0))
        )
        
        # Leverage ratios
        ratios['debt_to_equity'] = self.leverage.debt_to_equity(
            data.get('total_debt', Decimal(0)),
            data.get('shareholders_equity', Decimal(0))
        )
        
        # Valuation ratios
        ratios['pe_ratio'] = self.valuation.pe_ratio(
            data.get('price', Decimal(0)),
            data.get('eps', Decimal(0))
        )
        
        # Convert Decimal to float for JSON serialization
        return {k: float(v) if v is not None else None for k, v in ratios.items()}
